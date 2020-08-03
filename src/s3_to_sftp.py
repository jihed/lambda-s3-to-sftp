"""
AWS Lambda function for transferring files from S3 to SFTP on a create event.

Style note: the specific S3 interactions have been split out into very simple
one line functions - this is to make the code easier to read and test. It would
be perfectly valid to just have a single function that runs the entire thing.

Required env vars:

    SSH_HOSTNAME
    SSH_USERNAME
    SSH_PASSWORD or SSH_PRIVATE_KEY (S3 file path in 'bucket:key' format)

Optional env vars

    SSH_PORT - defaults to 22
    SSH_DIR - if specified the SFTP client will transfer the files to the
        specified directory.
    SSH_FILENAME - used as a mask for the remote filename. Supports three
        string replacement vars - {bucket}, {key}, {current_date}. Bucket
        and key refer to the uploaded S3 file. Current date is in ISO format.

"""
import datetime
import io
import logging
import os

import boto3
import botocore.exceptions
import paramiko

logger = logging.getLogger()
logger.setLevel(os.getenv('LOGGING_LEVEL', 'DEBUG'))

# read in shared properties on module load - will fail hard if any are missing
SSH_HOST = os.environ['SSH_HOST']
SSH_USERNAME = os.environ['SSH_USERNAME']
# must have one of pwd / key - fail hard if both are missing
SSH_PASSWORD = os.getenv('SSH_PASSWORD')
# path to a private key file on S3 in 'bucket:key' format.
SSH_PRIVATE_KEY = os.getenv('SSH_PRIVATE_KEY')
assert SSH_PASSWORD or SSH_PRIVATE_KEY, "Missing SSH_PASSWORD or SSH_PRIVATE_KEY"
# optional
SSH_PORT = int(os.getenv('SSH_PORT', 22))
SSH_DIR = os.getenv('SSH_DIR')
# filename mask used for the remote file
SSH_FILENAME = os.getenv('SSH_FILENAME', 'data_{current_date}')


def on_trigger_event(event, context):
    """
    Move uploaded S3 files to SFTP endpoint, then delete.

    This is the Lambda entry point. It receives the event payload and
    processes it. In this case it receives a set of 'Record' dicts which
    should contain details of an S3 file create event. The contents of this
    dict can be found in the tests.py::TEST_RECORD - the example comes from
    the Lambda test event rig.

    The only important information we process in this function are the
    `eventName`, which must start with ObjectCreated, and then the bucket name
    and object key.

    This function then connects to the SFTP server, copies the file across,
    and then (if successful), deletes the original. This is done to prevent
    sensitive data from hanging around - it basically only exists for as long
    as it takes Lambda to pick it up and transfer it.

    See http://docs.aws.amazon.com/lambda/latest/dg/python-programming-model-handler-types.html

    Args:
        event: dict, the event payload delivered by Lambda.
        context: a LambdaContext object - unused.

    """
    if SSH_PRIVATE_KEY:
        key_obj = get_private_key(*SSH_PRIVATE_KEY.split(':'))
    else:
        key_obj = None

    # prefix all logging statements - otherwise impossible to filter out in
    # Cloudwatch
    logger.info(f"S3-SFTP: received trigger event")

    sftp_client, transport = connect_to_sftp(
        hostname=SSH_HOST,
        port=SSH_PORT,
        username=SSH_USERNAME,
        password=SSH_PASSWORD,
        pkey=key_obj
    )
    if SSH_DIR:
        sftp_client.chdir(SSH_DIR)
        logger.debug(f"S3-SFTP: Switched into remote SFTP upload directory")

    with transport:
        for s3_file in s3_files(event):
            filename = sftp_filename(SSH_FILENAME, s3_file)
            bucket = s3_file.bucket_name
            contents = ''
            try:
                logger.info(f"S3-SFTP: Transferring S3 file '{s3_file.key}'")
                transfer_file(sftp_client, s3_file, filename)
            except botocore.exceptions.BotoCoreError as ex:
                logger.exception(f"S3-SFTP: Error transferring S3 file '{s3_file.key}'.")
                contents = str(ex)
                filename = filename + '.x'
            logger.info(f"S3-SFTP: Archiving S3 file '{s3_file.key}'.")
            archive_file(bucket=bucket, filename=filename, contents=contents)
            logger.info(f"S3-SFTP: Deleting S3 file '{s3_file.key}'.")
            delete_file(s3_file)


def connect_to_sftp(hostname, port, username, password, pkey):
    """Connect to SFTP server and return client object."""
    transport = paramiko.Transport((hostname, port))
    transport.connect(username=username, password=password, pkey=pkey)
    client = paramiko.SFTPClient.from_transport(transport)
    logger.debug(f"S3-SFTP: Connected to remote SFTP server")
    return client, transport


def get_private_key(bucket, key):
    """
    Return an RSAKey object from a private key stored on S3.

    It will fail hard if the key cannot be read, or is invalid.

    """
    key_obj = boto3.resource('s3').Object(bucket, key)
    key_str = key_obj.get()['Body'].read().decode('utf-8')
    key = paramiko.RSAKey.from_private_key(io.StringIO(key_str))
    logger.debug(f"S3-SFTP: Retrieved private key from S3")
    return key


def s3_files(event):
    """
    Iterate through event and yield boto3.Object for each S3 file created.

    This function loops through all the records in the payload,
    checks that the event is a file creation, and if so, yields a
    boto3.Object that represents the file.

    NB Redshift will trigger an `ObjectCreated:CompleteMultipartUpload` event
    will UNLOADing the data; if you select to dump a manifest file as well,
    then this will trigger `ObjectCreated:Put`

    Args:
        event: dict, the payload received from the Lambda trigger.
            See tests.py::TEST_RECORD for a sample.

    """
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        event_category, event_subcat = record['eventName'].split(':')
        if event_category == 'ObjectCreated':
            logger.info(f"S3-SFTP: Received '{ event_subcat }' trigger on '{ key }'")
            yield boto3.resource('s3').Object(bucket, key)
        else:
            logger.warning(f"S3-SFTP: Ignoring invalid event: { record }")


def sftp_filename(file_mask, s3_file):
    """Create destination SFTP filename."""
    return file_mask.format(
        bucket=s3_file.bucket_name,
        key=s3_file.key.replace("_000", ""),
        current_date=datetime.date.today().isoformat()
    )


def transfer_file(sftp_client, s3_file, filename):
    """
    Transfer S3 file to SFTP server.

    Args:
        sftp_client: paramiko.SFTPClient, connected to SFTP endpoint
        s3_file: boto3.Object representing the S3 file
        filename: string, the remote filename to use

    Returns a 2-tuple containing the name of the remote file as transferred,
        and any status message to be written to the archive file.

    """
    with sftp_client.file(filename, 'w') as sftp_file:
        s3_file.download_fileobj(Fileobj=sftp_file)
    logger.info(f"S3-SFTP: Transferred '{ s3_file.key }' from S3 to SFTP as '{ filename }'")


def delete_file(s3_file):
    """
    Delete file from S3.

    This is only a one-liner, but it's pulled out into its own function
    to make it easier to mock in tests, and to make the trigger
    function easier to read.

    Args:
        s3_file: boto3.Object representing the S3 file

    """
    try:
        s3_file.delete()
    except botocore.exceptions.BotoCoreError as ex:
        logger.exception(f"S3-SFTP: Error deleting '{ s3_file.key }' from S3.")
    else:
        logger.info(f"S3-SFTP: Deleted '{ s3_file.key }' from S3")


def archive_file(*, bucket, filename, contents):
    """
    Write to S3 an archive file.

    The archive does **not** contain the file that was sent, as we don't
    want the data hanging around on S3. Instead it's just an empty marker
    that represents the file. If the transfer errored, then the archive file
    has a '.x' suffix, and will contain the error message.

    Args:
        bucket: string, S3 bucket name
        filename: string, the name of the archive file
        contents: string, the contents of the archive file - blank unless there
            was an exception, in which case the exception message.

    """
    key = 'archive/{}'.format(filename)
    try:
        boto3.resource('s3').Object(bucket, key).put(Body=contents)
    except botocore.exceptions.BotoCoreError as ex:
        logger.exception(f"S3-SFTP: Error archiving '{ filename }' as '{ key }'.")
    else:
        logger.info(f"S3-SFTP: Archived '{ filename }' as '{ key }'.")
