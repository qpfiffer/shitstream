import re

class downloader(object):
    def download(self, url, target, emit):
        raise NotImplementedError

    def __unicode__(self):
        raise NotImplementedError

    def __str__(self):
        return self.__unicode__()
