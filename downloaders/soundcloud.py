from downloader import downloader
import json, requests, re

class soundcloud_downloader(downloader):
    # https://soundcloud.com/neet/im-coming-too
    regex = re.compile("https?://(www\.)?soundcloud.com/.*")

    def download(self, url, target, emit):
        page = requests.get(url)
        raise NotImplementedError

    def __unicode__(self):
        return "soundcloud-dl"

