#!/usr/bin/env python

# Copyright (c) 2021 Dennis Mellican
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import Flask, render_template, url_for, copy_current_request_context, redirect
from threading import Thread, Event

from slack_sdk.web import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

import logging
from logging.config import dictConfig
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import yaml

class Config():

    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if Path(current_dir + '/config.yml').is_file():
            self.config_file = current_dir + '/config.yml'

        # For Docker config mount volume
        if Path('/config/config.yml').is_file():
            self.config_file = '/config/config.yml'
        self.last_updated = ''

    def load_config(self):
        """Load config file if it has changed.
        """
        if (self.last_updated != os.stat(self.config_file).st_mtime):
            with open(self.config_file, 'r') as stream:
                self.config = yaml.load(stream, Loader=yaml.FullLoader)
            self.last_updated = os.stat(self.config_file).st_mtime
            return self.config

config_file = Config()
config_file.load_config()
config = config_file.config

if 'loglevel' in config:
    loglevel = config['loglevel']
else:
    loglevel = 'INFO'

logging.config.dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s: %(message)s',
    }},
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stdout',
        },
        'logfile': {
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'slackview.log',
            'mode': 'a',
            'maxBytes': 1048576,
            'backupCount': 10
        }
    },
    'root': {
        'level': loglevel,
        'handlers': ['console','logfile']
    }
})
logging.getLogger('werkzeug').disabled = True
logger = logging.getLogger(__name__)
os.environ['WERKZEUG_RUN_MAIN'] = 'true'

def in_config(key):
    if key in config:
        return True
    else:
        return False

def terminate(message):
    logging.error(message)
    sys.exit()

def pre_flight_check():
  if not in_config("slack_bot_token"):
      terminate("[ERROR] slack_bot_token not defined in config.yml file.")

  if not in_config("slack_app_token"):
      terminate("[ERROR] slack_bot_token not defined in config.yml file.")

  if not in_config("history_limit"):
      logger.info("history_limit not defined, defaulting to 50.")
      config["history_limit"] = 50

  if not in_config("theme"):
      logger.info("theme not defined, defaulting to 'styles'.")
      config["theme"] = "styles"
  config["theme"] = config["theme"].replace("\.css$",'')

pre_flight_check()

global all_emojis
global user_list

socketClient = SocketModeClient(
    app_token=config['slack_app_token'],
    web_client=WebClient(token=config['slack_bot_token'])
)
webClient = WebClient(token=config['slack_bot_token'])

def channel_list():
    try:
        result = webClient.conversations_list()
        return result['channels']
    except SlackApiError as e:
        logger.error("Error fetching channels: {}".format(e))
        return

def get_channel_by_id(slackChannelId):
    try:
        result = webClient.conversations_list()
        for channel in result['channels']:
            if channel["id"] == slackChannelId:
                return channel
    except SlackApiError as e:
        logger.error("Error fetching channels: {}".format(e))

def get_channel_by_name(slackChannelName):
    try:
        result = webClient.conversations_list()
        for channel in result['channels']:
            if channel["name"] == slackChannelName:
                return channel
    except SlackApiError as e:
        logger.error("Error fetching channels: {}".format(e))

def get_channel_history(channel_id, history_count):
    conversation_history = []
    try:
        result = webClient.conversations_history(channel=channel_id,limit=history_count)
        conversation_history = list(reversed(result["messages"]))
    except SlackApiError as e:
        logger.error("Error creating conversation: {}".format(e))
    
    message_cache_file = ".channel-cache.tmp.json"
    try:
        with open(message_cache_file, 'w') as f:
            json.dump(conversation_history, f, indent=4, sort_keys=True)
    except Exception as e:
        logger.error("Could not write message cache file: %s" % e)

    return conversation_history

def render_message(message):
    logger.debug("Message to render: %s" % message)
    if message["type"] == "message" \
        and message.get("subtype") is None:
         payload = render_user_message(message)
         socketio.emit('newmessage', {'text': payload}, namespace='/watch', room=room)

    # Process bot messages
    if message["type"] == "message" \
        and message.get("subtype") == "bot_message":
         payload = render_bot_message(message)
         socketio.emit('newmessage', {'text': payload}, namespace='/watch', room=room)

def get_all_users():
    users_cache_file = ".users-cache.tmp.json"
    try:
        with open(users_cache_file) as f:
            data = json.load(f)
        return data
    except Exception:
        pass

    try:
        result = webClient.users_list()
    except SlackApiError as e:
        logger.error("Error retrieving user list: {}".format(e))

    userlistIndexed = {}
    for user in result['members']:
        userlistIndexed[user['id']] = user

    try:
        with open(users_cache_file, 'w') as f:
            json.dump(userlistIndexed, f, indent=4, sort_keys=True)
    except Exception as e:
        logger.error("Could not write users cache file: %s" % e)

    return userlistIndexed

def user_id_to_name(userId):
    user = user_list[userId];
    if "real_name" in user:
        return user['real_name']
    if "name" in user:
        return user['name']
    return 'Unknown';

def get_all_emojis():
    emoji_cache_file = ".emoji-cache.tmp.json"
    emojis_json = "emojis.json"
    try:
        with open(emoji_cache_file) as f:
            data = json.load(f)
        return data
    except Exception:
        pass
    
    try:
        result = webClient.emoji_list()
    except SlackApiError as e:
        logger.error("Error retrieving emoji list: {}".format(e))

    all_emojis = result['emoji']

    try:
        with open(emojis_json) as f:
            standard_emojis = json.load(f)
    except Exception as e:
        logger.error("Could not read emojis.json: %s" % e)
    for emoji in standard_emojis:
        as_html = "&#x" + emoji["unified"].replace('-',';&#x') + ";"
        all_emojis[emoji["short_name"]] = as_html                

    try:
        with open(emoji_cache_file, 'w') as f:
            json.dump(all_emojis, f, indent=4, sort_keys=True)
    except Exception as e:
        logger.error("Could not write emojis cache file: %s" % e)

    return all_emojis

def render_avatar(user):
    return '<img class="avatar" src="' + user['profile']['image_48'] + '" aria-hidden="true" title="">'

def render_icon(icon):
    icon = icon.replace(':','').lower()
    return '<span class="emoji">' + all_emojis[icon] + '</span>'

def replace_markdown(message):

    # Replace :emoji:
    matches = re.findall(':([a-zA-Z0-9_\-]+)(::[a-zA-Z0-9_\-])?:', message)
    for icon in matches:
        try:
            message = message.replace(':' + icon[0] + ':',all_emojis[icon[0].lower()])
        except Exception:
            pass

    # Replace *bold* with <b>bold</b>
    message = re.sub(r"\*([^\*]*)\*", r"<b>\1</b>", message)

    # Replace _italics_ with <i>italicsl</i>
    message = re.sub(r"\_([^\*]*)\_", r"<i>\1</i>", message)

    return message

def render_user_message(message):
    html = '<div class="slack-message">'
    html += render_avatar(user_list[message['user']])
    html += '<div class="content">'
    html += '<strong class="username">' + user_id_to_name(message['user']) + '</strong> '
    timeArray = time.localtime(float(message['ts']))
    html += '<small class="timestamp">' + time.strftime("%Y-%m-%d %H:%M:%S", timeArray) + '</small>'
    html += '<small class="timestamp">' + time.strftime("%Y-%m-%d %H:%M:%S", timeArray) + '</small>'
    html += '<div class="message">' + replace_markdown(message["text"]) + '</div>'
    html += '</div>'
    html += '</div>'
    return html

def render_bot_message(message):
    html = '<div class="slack-message">'
    try:
        if "emoji" in message['icons']:
            icon = message['icons']['emoji']
            html += render_icon(icon)
        elif "image_64" in message["icons"]:
            message['icons']['image_64']
            html += '<img class="avatar" src="' + message['icons']['image_64'] + '" aria-hidden="true" title="">'
    except Exception as e:
        #TODO: Find bot_id icon image.
        logger.warning("Could not find an emoji / icon %s" % e)
    html += '<div class="content">'
    html += '<strong class="username">' + message['username'] + '</strong> '
    timeArray = time.localtime(float(message['ts']))
    html += '<small class="timestamp">' + time.strftime("%Y-%m-%d %H:%M:%S", timeArray) + '</small>'
    html += '<div class="message">' + replace_markdown(message["text"]) + '</div>'
        
#TODO
#    if (isset($message['reactions'])) {
#        $html .= render_reactions($message['reactions']);
#    }
    html += '</div>'
    html += '</div>'
    return html

def process(client: SocketModeClient, req: SocketModeRequest):
    if req.type == "events_api":
        logger.debug("Event detected: %s" % req.payload["event"])
        # Acknowledge the request anyway
        response = SocketModeResponse(envelope_id=req.envelope_id)
        socketClient.send_socket_mode_response(response)

        # Process user messages
        if req.payload["event"]["type"] == "message" \
            and req.payload["event"].get("subtype") is None:
             payload = render_user_message(req.payload["event"])
             room_name = get_channel_by_id(req.payload["event"].get("channel"))
             socketio.emit('newmessage', {'text': payload}, namespace='/watch', room=room_name['name'])

        # Process bot messages
        if req.payload["event"]["type"] == "message" \
            and req.payload["event"].get("subtype") == "bot_message":
             payload = render_bot_message(req.payload["event"])
             room_name = get_channel_by_id(req.payload["event"].get("channel"))
             socketio.emit('newmessage', {'text': payload}, namespace='/watch', room=room_name['name'])

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['DEBUG'] = True

socketio = SocketIO(app, async_mode=None, logger=True, engineio_logger=True)

thread = Thread()
thread_stop_event = Event()

def watch_slack():
    socketClient.socket_mode_request_listeners.append(process)
    socketClient.connect()
    Event().wait()

@app.route('/')
def index():
    if 'channel_default' in config:
        return redirect('/slackview/' + config['channel_default'], 307)
    else:
        return render_template('index.html',
                               channels=channel_list())

@app.route('/slackview/<channel_name>')
def watch(channel_name):
    global channel
    global channel_history
    channel = get_channel_by_name(channel_name)
    channel_history = get_channel_history(channel['id'],config['history_limit'])
    return render_template('slackview.html',
                           theme=config['theme'])

@socketio.on('join', namespace='/watch')
def watch_connect(data):
    global thread
    global room
    global room_id
    room = data['channel']
    join_room(room)
    logger.info("Client connected to %s" % room)

    if not thread.is_alive():
        thread = socketio.start_background_task(watch_slack)

    for message in channel_history:
        render_message(message);

@socketio.on('disconnect', namespace='/watch')
def watch_disconnect(data):
    room = data['channel']
    join_room(room)
    logger.info('Client disconnected')

if __name__ == '__main__':
    logger.info("Slackviewer is ready")
    all_emojis = get_all_emojis()
    user_list = get_all_users()
    socketio.run(app, host='0.0.0.0', port=7000)
