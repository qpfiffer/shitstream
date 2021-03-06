#!flask/bin/python

from functools import wraps
import glob
import os
import threading
import time

from flask import Flask, jsonify, request, send_file
from flask.ext.conditional import conditional
from flask.ext.socketio import SocketIO, emit
from flask.ext import restless
from lxml import html
import requests

from downloaders.youtube import youtube_downloader
from downloaders.soundcloud import soundcloud_downloader
from emberify import emberify
from mpd_util import mpd, mpd_connect
import settings


def create_app():

    app = Flask(__name__)
    if settings.debug:
        app.debug = True
    app.config['SECRET_KEY'] = 'secret!'
    app.config['SQLALCHEMY_DATABASE_URI'] = settings.db_uri
    app.downloaders = [youtube_downloader, soundcloud_downloader]
    return app

app = create_app()
import db

api_prefix = '/api/v1.0'
socketio = SocketIO(app)

def api_route(route, *args, **kwargs):
    def wrapper(function):
        @app.route(api_prefix + route, *args, **kwargs)
        @wraps(function)
        def route_fn(*args, **kwargs):
            return function(*args, **kwargs)
        return route_fn
    return wrapper


@app.route('/')
def index():
    return send_file('index.html')


@api_route('/queue/<queue_id>', methods=['DELETE'])
@mpd
def del_song_from_queue(queue_id, mpdc=None):
    queue = db.Queue.query.filter(db.Queue.id == queue_id).one()
    mpdc.deleteid(queue.id)
    return jsonify({})


@api_route('/queue', methods=['POST'])
@mpd
def add_song_to_queue(mpdc=None):
    song_id = request.json['queue']['song']
    song = db.Song.query.filter(db.Song.id == song_id).one()
    queue_id = int(mpdc.addid(song.uri))
    queue_data = mpdc.playlistid(queue_id)[0]
    if not mpdc.currentsong():
        mpdc.playid(queue_id)

    return jsonify({'queue': {
        'id': queue_id,
        'pos': queue_data['pos'],
        'song': song_id
    }})


@socketio.on('connect', namespace = api_prefix + '/add_url/')
def add_url_connect():
    emit('response', {'msg': 'Connected'});

@mpd
def update_mpd(uri=None, updating=None, mpdc=None):
    job = mpdc.update(uri)
    added = False
    while not added:
        cur_job = mpdc.status().get('updating_db')
        if (cur_job and cur_job <= job):
            if updating:
                updating()
            time.sleep(1)
        else:
            added = True

@mpd
@socketio.on('add_url', namespace = api_prefix + '/add_url/')
def add_url_event(msg, mpdc=None):
    in_dir = settings.download_dir
    music_dir = settings.mpd_dir

    if not msg:
        emit('response', {'msg': 'No URL received'})
        return

    url = msg.get('url', None)
    if not url:
        emit('response', {'msg': 'No URL received'})
        return

    emit('response', {'msg': 'Received URL'})

    # See if any REGEX match:
    matched = False
    matched_downloader = None
    for downloader in app.downloaders:
        if downloader.regex.match(url):
            matched = True
            matched_downloader = downloader()

    # Nobody matched, ya dun fucked up
    if not matched:
        emit('response', {'msg': 'URL does not appear to be valid'})
        return

    emit('response', {'msg': 'URL appears to be valid'})
    emit('response', {'msg': 'Starting {}'.format(matched_downloader)})

    try:
        filename = matched_downloader.download(url, in_dir, emit)
    except Exception as exception:
        emit('response', {'msg': str(exception)})
        emit('disconnect')
        return

    common = os.path.commonprefix([in_dir, music_dir])
    uri = filename.replace(common, '')
    mpdc = mpd_connect()
    if uri[0] == '/':
        uri = uri[1:]

    # Add song to MPD
    emit('response', {'msg': 'Adding song to music database'})
    update_mpd(uri,
        emit('response', {'msg': 'Music database still updating'}))
    emit('response', {'msg': 'Song added to music database'})

    # Add song to database
    song = mpdc.listallinfo(uri)[0]
    db.new_song_from_mpd_data(song)
    db.db.session.commit()

    # Add song to Queue
    emit('response', {'msg': 'Adding song to queue'})
    songid = mpdc.addid(uri)
    if not mpdc.currentsong():
        mpdc.playid(songid)
    emit('response', {'msg': 'Song queued'})

    emit('disconnect')

@api_route('/listeners')
def get_listeners():
    try:
        url = settings.icecast_status_url
        page = requests.get(url)
        tree = html.fromstring(page.text)
        elem = tree.xpath('//td[text()="Current Listeners:"]/following-sibling::td')
        return jsonify({'listeners':elem[0].text})
    except:
        return jsonify({'listeners': None})


##
## Test methods, enabled only if debug is True
##
@conditional(app.route('/tests'), app.debug)
def tests():
    return send_file('tests.html')


@conditional(app.route('/tests/reset'), app.debug)
@mpd
def tests_reset(mpdc=None):
    files_glob = os.path.join(settings.download_dir, '*')
    files = glob.glob(files_glob)
    for f in files:
        os.remove(f)
    update_mpd(mpdc=mpdc)
    mpdc.clear()
    return jsonify({'status': 'OK'})


def init():
    db.db.create_all()
    if settings.db_clear_on_load:
        db.clear_db_songs()

    queue_updates = threading.Thread(target=db.update_queue_on_change)
    queue_updates.start()

    song_updates = threading.Thread(target=db.update_songs_on_change)
    song_updates.start()

    manager = restless.APIManager(app, flask_sqlalchemy_db=db.db)

    #FIXME: copypaste
    manager.create_api(
        db.Artist,
        methods=['GET'],
        url_prefix=api_prefix,
        collection_name='artists',
        postprocessors={
            'GET_MANY': [emberify('artists', db.Artist)],
            'GET_SINGLE': [emberify('artist', db.Artist, many=False)]
        },
        results_per_page=None
    )
    manager.create_api(
        db.Song,
        methods=['GET'],
        url_prefix=api_prefix,
        collection_name='songs',
        postprocessors={
            'GET_MANY': [emberify('songs', db.Song)],
            'GET_SINGLE': [emberify('song', db.Song, many=False)]
        },
        results_per_page=None
    )
    manager.create_api(
        db.Album,
        methods=['GET'],
        url_prefix=api_prefix,
        collection_name='albums',
        postprocessors={
            'GET_MANY': [emberify('albums', db.Album)],
            'GET_SINGLE': [emberify('album', db.Album, many=False)]
        },
        results_per_page=None
    )
    manager.create_api(
        db.Queue,
        methods=['GET'],
        url_prefix=api_prefix,
        collection_name='queue',
        postprocessors={
            'GET_MANY': [emberify('queue', db.Queue)],
            'GET_SINGLE': [emberify('queue', db.Queue, many=False)]
        },
        results_per_page=None
    )


if __name__ == '__main__':
    init()
    socketio.run(app)
