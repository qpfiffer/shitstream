from downloader import downloader
import json, requests, re

class soundcloud_downloader(downloader):
    regex = re.compile("https?://(www\.)?soundcloud.com/.*")

    def download(self, url, target, emit):
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        page = requests.get(url, headers=headers)
        raise NotImplementedError

    def __unicode__(self):
        return "soundcloud-dl"

