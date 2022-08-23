#!/usr/bin/env python3
"""cligh — Command line interface to GitHub

Usage:
  cligh batch-clone --target=<dir> [--filter=<regex>]
  cligh config
  cligh collabs [--filter=<regex>]
  cligh collabs leave [--all] [--filter=<regex>]
  cligh invitations [--filter=<regex>]
  cligh invitations accept [--all] [--filter=<regex>]
  cligh invitations decline [--all] [--filter=<regex>]
  cligh user repos [--user=<user>] [--filter=<regex>]
  cligh user repos clone [--user=<user>] [--target=<dir>] [--filter=<regex>]
"""

import json
import os
import re
import requests
import sys

from docopt import docopt
from pathlib import Path

CONFIG_PATH = os.path.join(Path.home(), ".cligh")
CONFIG_FILE_NAME = "config.json"
CONFIG_FILE_PATH = os.path.join(CONFIG_PATH, CONFIG_FILE_NAME)

TTY_RED = "\033[91m"
TTY_ORANGE = "\u001b[31;1m"
TTY_GREEN = "\033[92m"
TTY_END = "\033[0m"

V4_API_BASE = "https://api.github.com/graphql"
V3_API_BASE = "https://api.github.com"

cfg = {}
v4headers = {}
v3headers = {
    "Accept" : "application/vnd.github.v3+json"
}

def creds_are_missing():
    return not 'github_user' in cfg or not cfg['github_user'] \
        or not 'github_token' in cfg or not cfg['github_token']

def load_config(force_prompt=False):

    def _load_config():
        global cfg
        with open(CONFIG_FILE_PATH) as config_file:
            cfg = json.load(config_file)

    def config_exists():
        return os.path.exists(CONFIG_FILE_PATH)

    if not config_exists():
        print("This must be your first time running cligh!  Take a second to do some configuration...")
        Path(CONFIG_PATH).mkdir(parents=True, exist_ok=True)
        prompt_config()
        _load_config()
    elif force_prompt:
        _load_config()
        prompt_config(cfg)
        _load_config()
    else:
        _load_config()


def prompt_config(defaults=None):

    cfg['github_user'] = prompt_def("What is your GitHub username? {}", defaults['github_user'] if defaults else "")
    cfg['github_token'] = prompt_def("What is your GitHub access token? {}")
    cfg['github_username_file'] = prompt_def("What name will you use for GitHub username files? {}", defaults['github_username_file'] if defaults else "")

    print("Saving conifuration to {}".format(CONFIG_FILE_PATH))
    with open(CONFIG_FILE_PATH, 'w+') as config_file:
        json.dump(cfg, config_file, indent=4, sort_keys=True)

def prompt_def(prompt, default=""):
    response = input(prompt.format(" [default:{}{}{}]".format(TTY_GREEN, default, TTY_END) if default else "") + " ")

    return response if response else default

def prompt(prompt, valid_options=[], default_option_index=-1):

    def there_is_a_default_option():
        return 0 <= default_option_index and default_option_index < len(opts)

    # copy the valid options so the comparison with the user's response doesn't fail
    # due to the coloring we're about to do
    opts = valid_options.copy()
    # color the default option
    if there_is_a_default_option():
        opts[default_option_index] = TTY_GREEN + opts[default_option_index] + TTY_END

    option_str = "[{}]".format("/".join(opts))

    while True:
        c = input("{} {} ".format(prompt, option_str))
        if ( c in valid_options ) :
            break
        elif ( there_is_a_default_option() and c == "" ) :
            c = valid_options[default_option_index]
            break

    return c

def query(q):
    return { "query" : " { " + q + " rateLimit { limit cost remaining resetAt } } " }

def exit_on_bad_response(response):
    if response.status_code >= 400:
        print("{}\n{}".format(response.status_code, response.text))
        exit(1)


def v3Url(q):
    return "{}{}".format(V3_API_BASE, q)

def v3request_all_pages(q, data=None):

    response = requests.get("{}{}".format(V3_API_BASE, q), headers=v3headers, params=data)

    fullresponse = response.json()

    while ( 'next' in response.links.keys() ):

        response = requests.get(response.links['next']['url'], headers=v3headers)
        fullresponse.extend(response.json())

    return fullresponse

def v4request(q):
    response = requests.post(V4_API_BASE, json=query(q), headers=v4headers)
    return response.json()

def v4request_all_pages(q, path_to_paginated_array):

    def get(json, path):

        keys = path.split(".")

        v = json

        for k in keys:
            v = v[k]

        return v


    def next_page(json, path_to_paginated_array):

        keys = path_to_paginated_array.split(".")
        # replace the paginated array node with the pageInfo node
        del keys[-1]
        keys.append('pageInfo')

        v = json

        for k in keys:
            v = v[k]

        if v['hasNextPage']:
            return v['endCursor']

        return None

    def merge(response_a, response_b, path_to_paginated_array):
        a = get(response_a, path_to_paginated_array)
        b = get(response_b, path_to_paginated_array)

        a += b

    responses = []

    path_to_paginated_array = "data." + path_to_paginated_array

    cursor = ""

    while True:
        formatted_q = q % (\
            ("after: \"{}\" ".format(cursor) if cursor else "") + "first: 50",\
            " pageInfo { endCursor hasNextPage } ")
        response = requests.post(V4_API_BASE, json=query(formatted_q), headers=v4headers)

        if response.status_code != 200:
            raise Exception("Request failed with code {}.\nRequest:\n{}\nResponse:\n{}".format(response.status_code, formatted_q, response))

        response_json = response.json()

        responses.append(response_json)

        cursor = next_page(response_json, path_to_paginated_array)
        if ( not cursor ) :
            break

    final_response = responses[0]
    del responses[0]

    for r in responses:
        merge(final_response, r, path_to_paginated_array)

    return final_response

def user_exists(user):
    response = v4request("user(login: \"{}\") {{ login }}".format(user))

    if ( 'errors' in response ):
        return False
    
    return True

def get_repos(user, filterRe=None):
    u = "user(login: \"{}\")".format(user)
    response = v4request_all_pages(u + """
                  {
                    repositories(%s) {
                      nodes  {
                        full_name: nameWithOwner
                        html_url: url
                      }
                      %s
                    }
                  }
            """, "user.repositories.nodes")

    ret = response['data']['user']['repositories']['nodes']

    if ( filterRe ):
        return [ r for r in ret if filterRe.search(r['full_name']) ]

    return ret

def invitation_name(i):
    return "{}/{}".format(i['inviter']['login'], i['repository']['name'] if i['repository'] else "")

def repo_name(r):
    return r['full_name']

def list_repos(user, filterRe=None):
    [ print(repo_name(r)) for r in get_repos(user, filterRe) ]

def pull_repo(target="."):
    cmd = "pushd {} && git pull && popd".format(target)
    print(cmd)
    os.system(cmd)

def clone_repos(user, target=None, filterRe=None):
    repos = get_repos(user, filterRe)

    if len(repos) == 0:
        print("No repos to clone")
        return

    which_repo = 1
    if len(repos) > 1:
        i = 1
        for r in repos:
            print("[{}] {} [{}]".format(i, r['html_url'], i))
            i += 1

        which_repo = int(prompt("Which repository would you like to clone{}?".format("into " + target if target else ""), 
            valid_options=[ str(i) for i in list(range(1, len(repos)+1)) ]))

    cmd = "git clone {} {}".format(repos[which_repo-1]['html_url'], target if target else "")
    print(cmd)
    os.system(cmd)

def batch_clone(target=None, filterRe=None):

    subdirs = [ d for d in os.listdir() if os.path.isdir(d) ]

    for d in subdirs:

        subdir_target = os.path.join(d, target if target else "")

        p = os.path.join(d, cfg['github_username_file'])
        if ( os.path.exists(p) ):

            with open(p, 'r') as github_login_file:

                user = github_login_file.read().replace('\n', '')

                if user == '' :
                    print("{}SKIPPING{} {} because the {} file was empty".format(TTY_RED, TTY_END, d, cfg['github_username_file']))
                    continue

                if not user_exists(user):
                    print("{}SKIPPING{} {} because no GitHub user {} exists".format(TTY_RED, TTY_END, d, user))
                    continue

                if os.path.exists(subdir_target):
                    print("{}PULLING{} ({} already exists)".format(TTY_RED, TTY_END, subdir_target))
                    pull_repo(subdir_target)
                    continue
                else:
                    print("{}CLONING{} into {}...".format(TTY_GREEN, TTY_END, subdir_target))
                    clone_repos(user, subdir_target, filterRe)
        else:
            print("{}SKIPPING{} {} because no {} file was found".format(TTY_RED, TTY_END, d, cfg['github_username_file']))
            continue

def get_collabs(filterRe=None):
    repos = v3request_all_pages("/user/repos", {"affiliation": "collaborator"})

    if ( filterRe ):
        return [ r for r in repos if filterRe.search(r['full_name']) ]

    return repos

def list_collabs(filterRe=None):
    [ print(repo_name(r)) for r in get_collabs(filterRe) ]

def leave_collab(owner_login, repo_name, leaving_user_login):
    response = requests.delete(v3Url("/repos/{}/{}/collaborators/{}".format(owner_login, repo_name, leaving_user_login)), headers=v3headers)
    exit_on_bad_response(response)

def leave_collabs(force=False, filterRe=None):
    repos = get_collabs(filterRe)

    if ( len(repos) == 0 ):
        print("No repos to leave")
        exit(0)

    if ( force ):
        [ print(repo_name(r)) for r in repos ]

        print()
        print("{}WARNING:{} You are about to {}LEAVE{} as a collaborator ALL {} of the above repositories."
            .format(TTY_ORANGE, TTY_END, TTY_RED, TTY_END, len(repos)))
        if ( 'y' == prompt("Are you sure you wish to continue?", ['y', 'n']) ):
            for r in repos:
                print("{}LEAVING{} {}...".format(TTY_RED, TTY_END, repo_name(r)), end="", flush=True)     
                leave_collab(r['owner']['login'], r['name'], cfg['github_user'])
                print("done")

    else: 
        for r in repos:

            if ( 'y' == prompt("Leave {}?".format(repo_name(r)), ['y','n'], default_option_index=0) ) :
                print("{}LEAVING{} {}...".format(TTY_RED, TTY_END, repo_name(r)), end="", flush=True)     
                leave_collab(r['owner']['login'], r['name'], cfg['github_user'])
                print("done")
            else:
                print("SKIPPED {}".format(repo_name(r)))

            print()

def get_invitations(filterRe=None):

    invitations = v3request_all_pages("/user/repository_invitations")
    
    if ( filterRe ): 
        return [ i for i in invitations if (filterRe.search(i['repository']['full_name']) if i['repository'] else False) ]
    else:
        return [ i for i in invitations if i['repository'] ]

    return invitations

def list_invitations(filterRe=None):
    [ print(invitation_name(i)) for i in get_invitations(filterRe) ]

def accept_invitation(invitation_id):
    response = requests.patch(v3Url("/user/repository_invitations/{}".format(invitation_id)), headers=v3headers)
    exit_on_bad_response(response)

def decline_invitation(invitation_id):
    response = requests.delete(v3Url("/user/repository_invitations/{}".format(invitation_id)), headers=v3headers)    
    exit_on_bad_response(response)

def accept_invitations(force=False, filterRe=None):

    invitations = get_invitations(filterRe)

    if ( len(invitations) == 0 ):
        print("No invitations to accept")
        exit(0)

    if ( force ):
        [ print(invitation_name(i)) for i in invitations ]

        print()
        print("{}WARNING:{} You are about to {}ACCEPT{} ALL {} of the above invitations."
            .format(TTY_ORANGE, TTY_END, TTY_GREEN, TTY_END, len(invitations)))
        if ( 'y' == prompt("Are you sure you wish to continue?", ['y', 'n']) ):
            for i in invitations:
                print("{}ACCEPTING{} {}...".format(TTY_GREEN, TTY_END, invitation_name(i)), end="", flush=True)     
                accept_invitation(i['id'])
                print("done")

    else: 
        for i in invitations:

            if ( 'y' == prompt("Accept {}?".format(invitation_name(i)), ['y','n'], default_option_index=0) ) :
                print("{}ACCEPTING{} {}...".format(TTY_GREEN, TTY_END, invitation_name(i)), end="", flush=True)     
                accept_invitation(i['id'])
                print("done")
            else:
                print("SKIPPED {}".format(invitation_name(i)))

            print()

def decline_invitations(force=False, filterRe=None):

    invitations = get_invitations(filterRe)

    if ( len(invitations) == 0 ):
        print("No invitations to decline")
        exit(0)

    if ( force ):

        [ print(invitation_name(i)) for i in invitations ]

        print()
        print("{}WARNING:{} You are about to {}DECLINE{} ALL {} of the above invitations."
            .format(TTY_ORANGE, TTY_END, TTY_RED, TTY_END, len(invitations)))
        if ( 'y' == prompt("Are you sure you wish to continue?", ['y', 'n']) ):
            for i in invitations:
                print("{}DECLINING{} {}...".format(TTY_RED, TTY_END, invitation_name(i)), end="", flush=True)     
                decline_invitation(i['id'])
                print("done")

    else:

        for i in invitations:

            if ( 'y' == prompt("Decline {}?".format(invitation_name(i)), ['y','n'], default_option_index=0) ) :
                print("{}DECLINING{} {}...".format(TTY_RED, TTY_END, invitation_name(i)), end="", flush=True)     
                decline_invitation(i['id'])
                print("done")

            else:
                print("SKIPPED {}".format(invitation_name(i)))

            print()

def cligh():

    args = docopt(__doc__, version="cligh 0.1")

    load_config(force_prompt=args['config'])

    v3headers['Authorization'] = "bearer " + cfg['github_token']
    v4headers['Authorization'] = "bearer " + cfg['github_token']

    user = cfg['github_user']

    if ( os.path.exists(cfg['github_username_file']) ):
        with open(cfg['github_username_file'], 'r') as github_login_file:
            user = github_login_file.read().replace('\n', '')
    
    if args['--user']:
        user = args['--user']

    if user and not user_exists(user):
        print("No GitHub user {} exists".format(user))
        return

    filterRe = re.compile(args['--filter'], re.IGNORECASE) if args['--filter'] else None

    force = args['--all']
    target = args['--target']


    try :

        if args['batch-clone']:
            batch_clone(target=target, filterRe=filterRe)

        elif args['collabs']:

            if args['leave']:
                leave_collabs(force=force, filterRe=filterRe)

            else :
                list_collabs(filterRe=filterRe)

        elif args['invitations']:

                if args['accept']:
                    accept_invitations(force=force, filterRe=filterRe)

                elif args['decline']:
                    decline_invitations(force=force, filterRe=filterRe)

                else :
                    list_invitations(filterRe=filterRe)

        elif args['user']:

            if args['repos']:

                if args['clone']:
                    clone_repos(user, target=target, filterRe=filterRe)

                else:
                    list_repos(user, filterRe=filterRe)

    except KeyboardInterrupt:
        sys.exit()

if __name__ == "__main__":
    cligh()