FROM python:3.9

WORKDIR /slackviewer
COPY . /slackviewer/

RUN pip3 install --upgrade pip wheel && pip3 install --upgrade -r requirements.txt

ENV PYTHONPATH="/config:$PYTHONPATH"

EXPOSE 7000

ENTRYPOINT [ "python3", "app.py" ]
