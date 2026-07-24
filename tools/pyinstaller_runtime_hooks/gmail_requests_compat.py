"""Restore the requests urllib3 compatibility alias in frozen builds."""

import sys

import requests.packages
import urllib3


sys.modules.setdefault("requests.packages.urllib3", urllib3)
requests.packages.urllib3 = urllib3
