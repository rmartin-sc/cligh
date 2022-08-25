#!/usr/bin/env python3

import inquirer
import json
import os
import re
import requests
import typer

from pathlib import Path
from rich import print
from rich.console import Console
from typing import Optional

console = Console()
app = typer.Typer()

collabs_app = typer.Typer(help="Perform operations on repositories for which you are a collaborator")
app.add_typer(collabs_app, name="collabs")

config_app = typer.Typer(help="Configure cligh")
app.add_typer(config_app, name="config")

invitations_app = typer.Typer(help="Handle invitations in bulk")
app.add_typer(invitations_app, name="invitations")

repos_app = typer.Typer(help="Bulk repo operations for a specific user or organization")
app.add_typer(repos_app, name="repos")


CONFIG_PATH = os.path.join(Path.home(), ".cligh")
CONFIG_FILE_NAME = "config.json"
CONFIG_FILE_PATH = os.path.join(CONFIG_PATH, CONFIG_FILE_NAME)

STR_ALL_HELP = "Process all items after a single confirmation instead of confirming for each item individually"
STR_FILTER_RE_HELP = "Only repos with names that contain this regex will be included in the results"
STR_IS_ORG_HELP = "If this option is on, the NAME argument is assumed to be an organization; otherwise, a user is assumed"
STR_NAME_HELP = "The name of a GitHub user or organization"
STR_TARGET_HELP = "The path in which to operate"


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


def open_json_file(file_path):
    with open(file_path) as file:
        return json.load(file)

def compile_re(re_str):
    return re.compile(re_str, re.IGNORECASE) if re_str else None

def spinner(message):
    return console.status(message, spinner="point")

def load_config():

    if not os.path.exists(CONFIG_FILE_PATH):
        print("This must be your first time running cligh!  Take a second to do some configuration...")
        Path(CONFIG_PATH).mkdir(parents=True, exist_ok=True)
        prompt_config()
        return open_json_file(CONFIG_FILE_PATH)
    else:
        return open_json_file(CONFIG_FILE_PATH)

@config_app.command("set")
def config_set():
    """Set cligh configuration"""
    existing_cfg = {}
    if os.path.exists(CONFIG_FILE_PATH):
        existing_cfg = open_json_file(CONFIG_FILE_PATH)
    prompt_config(existing_cfg)

@config_app.command("list")
def config_list():
    """List the current cligh configuration settings"""
    print(cfg)


def prompt_config(defaults=None):

    cfg['github_user'] = inquirer.text(message="What is your GitHub username?", default=defaults['github_user'] if defaults else ""),
    cfg['github_token'] = inquirer.text(message="What is your GitHub access token?"),
    cfg['github_username_file'] = inquirer.text(message="What name will you use for GitHub username files?", default=defaults['github_username_file'] if defaults else "")
    
    print(f"Saving conifuration to {CONFIG_FILE_PATH}")

    with open(CONFIG_FILE_PATH, 'w+') as config_file:
        json.dump(cfg, config_file, indent=4, sort_keys=True)

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

def user_exists(name):
    with spinner(f"Verifying GitHub user {name}"):
        response = v4request("user(login: \"{}\") {{ login }}".format(name))

    if ( 'errors' in response ):
        return False
    
    return True

def org_exists(name):
    with spinner("Verifying GitHub organization {name}"):
        response = v4request("organization(login: \"{}\") {{ login }}".format(name))

    if ( 'errors' in response ):
        return False
    
    return True

def get_repos(name, is_org, filter_re=None):

    entity = "organization" if is_org else "user"

    with spinner(f"Getting repos for {'organization' if is_org else 'user'} {name}"):
        response = v4request_all_pages(
            f'{entity}(login: "{name}")' 
            + """
                    {
                        repositories(%s) {
                        nodes  {
                            full_name: nameWithOwner
                            html_url: url
                        }
                        %s
                        }
                    }
                """, f"{entity}.repositories.nodes"
        )

    ret = response['data'][entity]['repositories']['nodes']

    if ( filter_re ):
        filter_re = compile_re(filter_re)
        return [ r for r in ret if filter_re.search(r['full_name']) ]

    return ret

def invitation_name(i):
    return "{}/{}".format(i['inviter']['login'], i['repository']['name'] if i['repository'] else "")

def repo_name(r):
    return r['full_name']

@repos_app.command("list")
def list_repos(
    name : str = typer.Argument(..., help=STR_NAME_HELP),
    is_org : Optional[bool] = typer.Option(False, "--org", help=STR_IS_ORG_HELP), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """List all repositories for a GitHub user or organization"""

    [ print(repo_name(r)) for r in get_repos(name, is_org, filter_re) ]

def pull_repo(target="."):
    cmd = "pushd {} && git pull && popd".format(target)
    print(cmd)
    os.system(cmd)

@repos_app.command("clone")
def clone_repos(
    name : str = typer.Argument(..., help=STR_NAME_HELP),
    into : Optional[Path] = typer.Argument(None, help="The name of the directory into which to clone the repo.  If this argument is specified, only one repository may be cloned. If it is not specified, multiple repos may be cloned into directories with the same names as the repos."),
    is_org : Optional[bool] = typer.Option(False, "--org", help=STR_IS_ORG_HELP), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk clone repos from a given user or organization"""

    repos = get_repos(name, is_org, filter_re)

    if len(repos) == 0:
        print("No repos to clone")
        return

    repo_idxs = [0]
    if len(repos) > 1:
        i = 1
        for r in repos:
            print("[{}] {} [{}]".format(i, r['html_url'], i))
            i += 1

        def get_repo_idx(repo_url):
            i = 0
            for r in repos:
                if r['html_url'] == repo_url:
                    return i
                i += 1

            return -1

        choices = [ r['html_url'] for r in repos ]

        if ( into ):
            chosen_repo = inquirer.list_input(f"Which repository would you like to clone into {into}?", choices=choices)
            repo_idxs = [ get_repo_idx(chosen_repo) ]
        else:
            chosen_repos = inquirer.checkbox(message="Which repositories would you like to clone?", choices=choices)
            repo_idxs = []
            for r in chosen_repos:
                repo_idxs.append(get_repo_idx(r))

            if len(repo_idxs) == 0:
                print("No repos to clone")

    print(repo_idxs)
    for i in repo_idxs:
        cmd = "git clone {} {}".format(repos[i]['html_url'], into if into else "")
        print(cmd)
        os.system(cmd)
            
@app.command()
def batch_get(
    into : Path = typer.Argument(..., help="The name of the subfolder into which to clone/pull"), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """For each subdirectory of the current working directory that contains a GitHub username file (as determined by the github_username_file config setting), clone (or pull if already cloned) the repositories for that GitHub user."""

    subdirs = [ d for d in os.listdir() if os.path.isdir(d) ]

    for d in subdirs:

        subdir_target = os.path.join(d, into if into else "")

        p = os.path.join(d, cfg['github_username_file'])
        if ( os.path.exists(p) ):

            with open(p, 'r') as github_login_file:

                user = github_login_file.read().replace('\n', '')

                if user == '' :
                    print("[bold red]SKIPPING[/bold red] {} because the {} file was empty".format(d, cfg['github_username_file']))
                    continue

                if not user_exists(user):
                    print("[bold red]SKIPPING[/bold red] {} because no GitHub user {} exists".format(d, user))
                    continue

                if os.path.exists(subdir_target):
                    print("[bold green]PULLING[/bold green] ({} already exists)".format(subdir_target))
                    pull_repo(subdir_target)
                    continue
                else:
                    print("[bold green]CLONING[/bold green] into {}...".format(subdir_target))
                    clone_repos(user, subdir_target, is_org=False, filter_re=filter_re)
        else:
            print("[bold red]SKIPPING[/bold red] {} because no {} file was found".format(d, cfg['github_username_file']))
            continue

def get_collabs(filter_re=None):
    with spinner("Finding collabs"):
        repos = v3request_all_pages("/user/repos", {"affiliation": "collaborator"})

    if ( filter_re ):
        filter_re = compile_re(filter_re)
        return [ r for r in repos if filter_re.search(r['full_name']) ]

    return repos

@collabs_app.command("list")
def list_collabs(filter_re:Optional[str]= typer.Option(None, help=STR_FILTER_RE_HELP)):
    """List all repositories for which you are a collaborator"""
    [ print(repo_name(r)) for r in get_collabs(filter_re) ]

def leave_collab(owner_login, repo_name, leaving_user_login):
    response = requests.delete(v3Url("/repos/{}/{}/collaborators/{}".format(owner_login, repo_name, leaving_user_login)), headers=v3headers)
    exit_on_bad_response(response)

@collabs_app.command("leave")
def leave_collabs(
    all : bool = typer.Option(False, help=STR_ALL_HELP),
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk remove yourself as a collaborator from a set of repositories"""
    repos = get_collabs(filter_re)

    if ( len(repos) == 0 ):
        print("No repos to leave")
        exit(0)

    if ( all ):
        [ print(repo_name(r)) for r in repos ]

        print()
        print("[bold yellow]WARNING:[/bold yellow] You are about to [bold red]LEAVE[/bold red] as a collaborator ALL {} of the above repositories."
            .format(len(repos)))
        if ( inquirer.confirm("Are you sure you wish to continue?") ):
            for r in repos:
                print("[bold red]LEAVING[/bold red] {}...".format(repo_name(r)), end="", flush=True)     
                leave_collab(r['owner']['login'], r['name'], cfg['github_user'])
                print("done")

    else: 
        for r in repos:

            if ( inquirer.confirm("Leave {}?".format(repo_name(r))) ) :
                print("[bold red]LEAVING[/bold red] {}...".format(repo_name(r)), end="", flush=True)     
                leave_collab(r['owner']['login'], r['name'], cfg['github_user'])
                print("done")
            else:
                print("SKIPPED {}".format(repo_name(r)))

            print()

def get_invitations(filter_re=None):

    with spinner("Finding invitations"):
        invitations = v3request_all_pages("/user/repository_invitations")
    
    if ( filter_re ): 
        filter_re = compile_re(filter_re)
        return [ i for i in invitations if (filter_re.search(i['repository']['full_name']) if i['repository'] else False) ]
    else:
        return [ i for i in invitations if i['repository'] ]

    return invitations

@invitations_app.command("list")
def list_invitations(filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)):
    """List current pending invitations"""

    [ print(invitation_name(i)) for i in get_invitations(filter_re) ]

def accept_invitation(invitation_id):
    response = requests.patch(v3Url("/user/repository_invitations/{}".format(invitation_id)), headers=v3headers)
    exit_on_bad_response(response)

def decline_invitation(invitation_id):
    response = requests.delete(v3Url("/user/repository_invitations/{}".format(invitation_id)), headers=v3headers)    
    exit_on_bad_response(response)

@invitations_app.command("accept")
def accept_invitations(
    all : Optional[bool] = typer.Option(False, help=STR_ALL_HELP), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk accept invitations"""

    invitations = get_invitations(filter_re)

    if ( len(invitations) == 0 ):
        print("No invitations to accept")
        exit(0)

    if ( all ):
        [ print(invitation_name(i)) for i in invitations ]

        print()
        print("[bold yellow]WARNING:[/bold yellow] You are about to [bold green]ACCEPT[/bold green] ALL {} of the above invitations."
            .format(len(invitations)))
        if ( inquirer.confirm("Are you sure you wish to continue?") ):
            for i in invitations:
                print("[bold green]ACCEPTING[/bold green] {}...".format(invitation_name(i)), end="", flush=True)     
                accept_invitation(i['id'])
                print("done")

    else: 
        for i in invitations:

            if ( inquirer.confirm("Accept {}?".format(invitation_name(i))) ) :
                print("[bold green]ACCEPTING[/bold green] {}...".format(invitation_name(i)), end="", flush=True)     
                accept_invitation(i['id'])
                print("done")
            else:
                print("SKIPPED {}".format(invitation_name(i)))

            print()

@invitations_app.command("decline")
def decline_invitations(
    all : Optional[bool] = typer.Option(False, help=STR_ALL_HELP), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk decline invitations"""
    
    invitations = get_invitations(filter_re)

    if ( len(invitations) == 0 ):
        print("No invitations to decline")
        exit(0)

    if ( all ):

        [ print(invitation_name(i)) for i in invitations ]

        print()
        print("[bold yellow]WARNING:[/bold yellow] You are about to [bold red]DECLINE[/bold red] ALL {} of the above invitations."
            .format(len(invitations)))
        if ( inquirer.confirm("Are you sure you wish to continue?") ):
            for i in invitations:
                print("[bold red]DECLINING[/bold red] {}...".format(invitation_name(i)), end="", flush=True)     
                decline_invitation(i['id'])
                print("done")

    else:

        for i in invitations:

            if ( inquirer.confirm("Decline {}?".format(invitation_name(i))) ) :
                print("[bold red]DECLINING[/bold red] {}...".format(invitation_name(i)), end="", flush=True)     
                decline_invitation(i['id'])
                print("done")

            else:
                print("SKIPPED {}".format(invitation_name(i)))

            print()

if __name__ == "__main__":
    cfg = load_config()

    v3headers['Authorization'] = "bearer " + cfg['github_token']
    v4headers['Authorization'] = "bearer " + cfg['github_token']

    user = cfg['github_user']

    if user and not user_exists(user):
        print("No GitHub user named '{}' exists".format(user))
    else:
        app()