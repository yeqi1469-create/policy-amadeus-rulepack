"""Verified-TLS read recovery for configured signed publication channels."""
from urllib.parse import urlparse

def get(url,**kwargs):
    import requests
    try:
        return requests.get(url,**kwargs)
    except (requests.Timeout,requests.ConnectionError):
        from rulepack_manager import _channel_config
        config=_channel_config()
        hosts={urlparse(config.get(key,'')).hostname for key in ('manifest_url','app_manifest_url')}
        hosts.add('raw.githubusercontent.com')
        if urlparse(url).scheme!='https' or urlparse(url).hostname not in hosts:
            raise
        direct=requests.Session()
        direct.trust_env=False
        # No verify=False, no credentials, no writes. Callers still verify
        # publisher signatures and complete payload SHA-256 before installation.
        return direct.get(url,**kwargs)
