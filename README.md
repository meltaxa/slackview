# Slack View

View a Slack channel in a web page.

The Slack View is not interactive. It is a read-only view of the target Slack channel leveraging the Slack API.

# Demo

A custom implementation of Slack View that live streams a #bad-actors Slack channel of hackers probing and attempting to infiltrate a system.
<p align="center"> 
<img src="https://mellican.com/badactors/images/badactors-example.png"/><br/>
An example of the Bad Actors Slack channel can be viewed in real time here: https://mellican.com/badactors
 </p>

## Pre-requisites

* A PHP server

## Installation

Copy the contents of this repository to your php web root folder.

## Configuration

### Update config.php 

* Change the timezone.
* Update the slackApiToken with the OAuth token (see below for details).
* Update slackChannelName in the config.php file with the Slack Channel Name you want published.
* Optional: Update the slackHistoryCount in the config.php file with how many messages to display.

config.php extract:
```php
$timezone = 'Australia/Brisbane';

$slackApiToken = 'TOKEN';
$slackChannelName = 'CHANNEL';

$slackHistoryCount = '50';

$cacheDirectory = sys_get_temp_dir();
```

#### To obtain a Slack API token:
1. Visit https://api.slack.com/apps
1. Click "Create New App"
1. Call the App "SlackView"
1. Under Features > OAuth & Permissions > Scopes, add the following OAuth scopes:

   * channels:history
   * channels:read
   * users:read
   * emoji:read

1. Click Install App to Workspace

   Accept permissions by clicking "Allow" button.

1. Copy the OAuth Access Token and update it in the config.php file.

#### Add SlackView to the channel

1. The SlackView "bot" app needs to join the channel by issuing the invite command from the channel:

   ```/invite @SlackView```

# Using Slack View

Visit your web page, either the index.html which demonstrates embedding the Slack channel as an IFrame and allows
the view to be refreshed automatically. 

Alternatively, the view can be called direct via the slackview.php page. This does not automatically refresh. Use a
method such as [livereload](https://github.com/livereload/livereload-js) to trigger updates.

By default the order of messages is in descending time order (oldest to latest). It can be set using the parameter order=asc|des (ascending or descending). For example, ```slackview.php?order=asc``` to order messages from latest to oldest.

# Acknowledgements

Forked from [hjnilsson's slack-web-viewer](https://github.com/hjnilsson/slack-web-viewer) project.
