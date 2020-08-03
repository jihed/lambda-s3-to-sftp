FROM  lambci/lambda:build-python3.8
RUN yum install -y zip && \
    yum install -y gcc libffi-devel python-devel OpenSSL-devel && \
    python3 -m pip install pip-tools
ENV LC_ALL=en_US.utf8