from install_steps import index_client
from azure.mgmt.network import NetworkResourceProviderClient, SecurityRule
from azure.mgmt.network.networkresourceprovider import SecurityRuleOperations
from azure.mgmt.common import SubscriptionCloudCredentials
from urllib2 import Request
from urllib2 import urlopen
from urllib import urlencode
import json
import yaml
import os


def get_token_from_client_credentials(endpoint, client_id, client_secret):
    payload = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'resource': 'https://management.core.windows.net/',
    }
    request = Request(endpoint)
    request.data = urlencode(payload)
    result = urlopen(request)
    return json.loads(result.read())['access_token']


def get_ha_proxy_address(ctx):
    client = index_client.IndexClient(ctx.meta['index-file'])
    manifest = client.find_by_release('elastic-runtime')
    settings = ctx.meta['settings']

    username = settings["username"]
    manifest_path = os.path.join("/home", username, 'manifests', manifest['file'])

    with open(manifest_path, 'r') as stream:
        content = stream.read()

        try:
            doc = yaml.load(content)
        except yaml.YAMLError as exc:
            print(exc)
            return None

    job = filter(lambda job: job['name'] == 'haproxy', doc['jobs'])[0]
    default_net = filter(lambda net: net['name'] == 'default', job['networks'])[0]
    return default_net['static_ips'][0]


def do_step(context):
    settings = context.meta['settings']

    # cf specific configuration (configure security groups for haproxy)
    subscription_id = settings['SUBSCRIPTION-ID']
    tenant = settings['TENANT-ID']
    endpoint = "https://login.microsoftonline.com/{0}/oauth2/token".format(tenant)
    client_token = settings['CLIENT-ID']
    client_secret = settings['CLIENT-SECRET']

    ha_proxy_address = get_ha_proxy_address(context)

    token = get_token_from_client_credentials(endpoint, client_token, client_secret)
    creds = SubscriptionCloudCredentials(subscription_id, token)

    network_client = NetworkResourceProviderClient(creds)
    rules_client = SecurityRuleOperations(network_client)

    rule = SecurityRule(
        description="",
        protocol="*",
        source_port_range="*",
        destination_port_range="80",
        source_address_prefix="*",
        destination_address_prefix=ha_proxy_address,
        access="Allow",
        priority=1100,
        direction="InBound"
    )

    rules_client.create_or_update("cf", settings['NSG-NAME-FOR-CF'], "http_inbound", rule)

    rule = SecurityRule(
        description="",
        protocol="*",
        source_port_range="*",
        destination_port_range="443",
        source_address_prefix="*",
        destination_address_prefix=ha_proxy_address,
        access="Allow",
        priority=1200,
        direction="InBound"
    )

    rules_client.create_or_update("cf", settings['NSG-NAME-FOR-CF'], "https_inbound", rule)

    return context
