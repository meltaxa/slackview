<?php

include_once('config.php');

date_default_timezone_set($timezone);

?>
<html>
<head>
<title>
<?php
echo "Slack | $slackChannelName"
?>
</title>
<link href="style.css" rel="stylesheet" />
</head>
<body>
<div id="main">
<?php

$channelCacheFilename = $cacheDirectory . '/.channel-cache.tmp.json';
$userlistCacheFilename = $cacheDirectory . '/.users-cache.tmp.json';
$emojiCacheFilename = $cacheDirectory . '/.emoji-cache.tmp.json';
$channelCacheTimeout = 60;
$userlistCacheTimeout = 300;
$emojiCacheTimeout = 3600;


function slack_api_request ($apiPath, $postFields) {
    global $slackApiToken;

    $postFields['token'] = $slackApiToken;
    
    $ch = curl_init('https://slack.com/api/' . $apiPath);
    $data = http_build_query($postFields);
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'POST');
    curl_setopt($ch, CURLOPT_POSTFIELDS, $data);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
    $result = curl_exec($ch);
    curl_close($ch);
    
    $result = json_decode($result, true);

    if ($result['ok'] == '1') {
        return $result;
    }
    
    print_r($result);
    die('Could not execute request ' . $apiPath);
}

function read_from_cache($cacheFilename, $cacheTimeout) {
    $lastModified = @filemtime($cacheFilename);
    if (!$lastModified) {
        return null;
    }

    if (time() - $lastModified > $cacheTimeout) {
        return null;
    }

    return json_decode(file_get_contents($cacheFilename), true);
}

function write_to_cache($cacheFilename, $cacheThisObject) {
    $f =  fopen($cacheFilename, 'w');
    fwrite($f, json_encode($cacheThisObject, JSON_PRETTY_PRINT));
    fclose($f);
}

function get_channel_history($channelId,$history_count)
{
    global $channelCacheFilename;
    global $channelCacheTimeout;


    $channel_history = read_from_cache($channelCacheFilename, $channelCacheTimeout);
    if ($channel_history) {
        return $channel_history;
    }

    $has_more = true;
    $channel_history = [];
    $fetch_from_ts = time();

    while ($has_more && count($channel_history) < $history_count) {
        $h = slack_api_request('conversations.history', [
            'channel' => $channelId,
            'count' => 1,
            'latest' => $fetch_from_ts,
        ]);

        $channel_history = array_merge($channel_history, $h['messages']);
        
        $has_more = $h['has_more'];
        $fetch_from_ts = array_slice($h['messages'], -1)[0]['ts'];
    }

    write_to_cache($channelCacheFilename, $channel_history);

    return $channel_history;
}

function get_all_emojis()
{
    global $emojiCacheFilename;
    global $emojiCacheTimeout;

    $all_emojis = read_from_cache($emojiCacheFilename, $emojiCacheTimeout);
    if ($all_emojis) {
        return $all_emojis;
    }

    $all_emojis = slack_api_request('emoji.list', [
        "channel" => $channelId,
    ]);

    $all_emojis = $all_emojis['emoji'];

    $standard_emojis = json_decode(file_get_contents("emojis.json"), true);
    foreach($standard_emojis as $e) {
        $as_html = '';

        $us = explode('-', $e['unified']);
        $as_html = '';
        foreach ($us as $u) {
            $as_html .= '&#x' . $u . ';';
        }

        foreach($e['short_names'] as $short_name) {
            $all_emojis[$short_name] = $as_html;
        }
    }

    $all['slightly_smiling_face'] = 'alias:wink';
    $all['white_frowning_face'] = 'alias:sad';

    write_to_cache($emojiCacheFilename, $all_emojis);

    return $all_emojis;
}

function get_all_users()
{
    global $userlistCacheFilename;
    global $userlistCacheTimeout;

    $userlist = read_from_cache($userlistCacheFilename, $userlistCacheTimeout);
    if ($userlist) {
        return $userlist;
    }

    $userlist = slack_api_request('users.list', [
        'limit' => 800,
        'presence' => false,
    ]);

    // Format in more sane way
    $userlistIndexed = [];
    foreach ($userlist['members'] as $user) {
        $userlistIndexed[$user['id']] = $user;
    }

    write_to_cache($userlistCacheFilename, $userlistIndexed);
    
    return $userlistIndexed;
}

function get_channel_by_name($channel_name) {
    $all_channels = slack_api_request('conversations.list', [
        'limit' => 500,
        'exclude_archived' => true
    ]);

    foreach ($all_channels['channels'] as $channel) {
        if ($channel['name'] == $channel_name) {
            return $channel;
        }
    }

    return null;
}

$channel = get_channel_by_name($slackChannelName);
$channel_history = get_channel_history($channel['id'],$slackHistoryCount);
$user_list = get_all_users();
$all_emojis = get_all_emojis();

function user_id_to_name($userId) {
    global $user_list;
    $user = $user_list[$userId];
    if ($user) {
        return $user['real_name'] ? $user['real_name'] : $user['name'];
    }
    else {
        return 'Unknown';
    }
}

function coloncode_to_emoji($coloncode) {
    global $all_emojis;

    $emoji = $all_emojis[$coloncode];
    if ($emoji) {
        if (substr($emoji, 0, 8) == 'https://') {
            return '<img class="emoji" src="' . $emoji . '" title="' . $coloncode . '">';
        }

        if (substr($emoji, 0, 6) == 'alias:') {
            return coloncode_to_emoji(substr($coloncode, 6));
        }
        
        return $emoji;

    }

    return ':' . $coloncode . ':'; 
}

function replace_slack_tags($text) {
    $text = preg_replace_callback(
        '/<@([a-zA-Z0-9]+)>/',
        function ($matches) {
            return user_id_to_name($matches[1]);
        },
        $text
    );
    
    $text = preg_replace_callback(
        '/:([a-zA-Z0-9_\-]+)(::[a-zA-Z0-9_\-])?:/',
        function ($matches) {
            return coloncode_to_emoji($matches[1]);
        },
        $text
    );
    
    $text = preg_replace_callback(
        '/<(https?:\/\/.+?)\\|([^>]+?)>/',
        function ($matches) {
            return ' <a target="_top" href="' . $matches['1'] . '" target="_blank">' . $matches[2] . '</a> ';
        },
        $text
    );
    
    $text = preg_replace_callback(
        '/<(https?:\/\/.+?)>/',
        function ($matches) {
            return ' <a target="_top" href="' . $matches['1'] . '" target="_blank">' . $matches[1] . '</a> ';
        },
        $text
    );

    $text = preg_replace(
        '/<#[a-zA-Z0-9]+\|([a-zA-Z0-9æøåÅÆØäöÄÖ\-_]+)>/',
        '#$1',
        $text
    );

    // 3+ are replaced with just two
    $text = preg_replace("/\n{3,}/", "\n\n", $text);

    return $text;
}

function render_reactions($reactions) {
    $html = '';
    foreach ($reactions as $r) {
        $emoji = $r['name'];
        $skin_modifier_pos = stripos($emoji, '::');
        if ($skin_modifier_pos) {
            $emoji = substr($emoji, 0, $skin_modifier_pos);
        }

        $html .= '<span class="reaction"><i title="' . $emoji . '">' . coloncode_to_emoji($emoji) . '</i> <small>' . $r['count'] . '</small>' . '</span>';
    }

    return $html;
}

function render_avatar($user) {
    return '<img class="avatar" src="' . $user['profile']['image_48'] . '" aria-hidden="true" title="">';
}

function render_userinfo($message, $user) {
    $html = '<strong class="username">' . user_id_to_name($user['id']) . '</strong> ';

    $html .= '<small class="timestamp">' . date('l, F jS \a\t g:i a', $message['ts']) . '</small>';

    return $html;
}

function render_user_message($message, $user) {
    $html = '<div class="slack-message">';

    if (isset($message['parent_user_id'])) {
        return '';
    }

    $html .= render_avatar($user);

    $html .= '<div class="content">';

    $html .= render_userinfo($message, $user);
    
    $html .= '<div class="message">' . replace_slack_tags($message['text']) . '</div>';
    
    if (isset($message['reactions'])) {
        $html .= render_reactions($message['reactions']);
    }

    $html .= '</div>'; // .content
    $html .= '</div>'; // .slack-message

    return $html;
}

function render_bot_message($message, $username) {
    $html = '<div class="slack-message">';
    if (isset($message['parent_user_id'])) {
        return '';
    }
    $html .= '<img class="avatar" src="' . $message['icons']['image_64'] . '" aria-hidden="true" title="">';
    $html .= '<div class="content">';
    $html .= '<strong class="username">' . $username . '</strong> ';
    $html .= '<small class="timestamp">' . date('l, F jS \a\t g:i a', $message['ts']) . '</small>';
    $html .= '<div class="message">' . replace_slack_tags($message['text']) . '</div>';
        
    if (isset($message['reactions'])) {
        $html .= render_reactions($message['reactions']);
    }
    $html .= '</div>'; // .content
    $html .= '</div>'; // .slack-message
    return $html;
}

function render_file_message($message, $user) {
    $file = $message['file'];
    $html = '<div class="slack-message">';

    $html .= render_avatar($user);
    
    $html .= '<div class="content file">';
    
    if ($file['pretty_type'] === 'Post') {
        $html .= render_userinfo($message, $user);
        $html .= '<div class="document">';
        $html .= '<h2>' . $file['title'] . '</h2>';
        $html .= '<hr>';
        $html .= $file['preview'];
        $html .= '<a class="readmore" target="_top" href="' . $file['permalink_public'] . '">Kilkk her for å lese hele posten</a>';
        $html .= '</div>';
    }
    else {
        $html .= '<div class="message">' . replace_slack_tags($message['text']) . '</div>';        
    }

    $html .= render_reactions($file['reactions']);

    $html .= '</div>'; // .content
    $html .= '</div>'; // .slack-message
    return $html;
}

function render_message($message, $user_list) {
    $html = '';

    switch ($message['type']) {
        case 'message':
            if (empty($message['subtype'])) {
                return render_user_message($message, $user_list[$message['user']]);                
            }

            switch($message['subtype']) {

                case 'file_share':
                    return render_file_message($message, $user_list[$message['user']]);
		case 'bot_message':
                    return render_bot_message($message, $message['username']);
                case 'channel_join':
                default:
                    return;
            }
            
        default:
            return;
    }
}

if ( isset($_GET['order']) ) {
            $order = $_GET['order'];
} else {
            $order = 'des';
}

if ( $order !== 'asc') {
    $channel_history = array_reverse($channel_history);
}

foreach ($channel_history as $message) {
    echo render_message($message, $user_list);
}

if ( $order !== 'asc') {
    ?>
    <script>
        window.scrollTo(0,document.body.scrollHeight);
        setTimeout(function() {
            // Allow images to load
            window.scrollTo(0,document.body.scrollHeight);
        }, 300);
    </script>
    <?php
}
?>
</div>
</div>
</body>
</html>
