#!/usr/bin/env python3

import cfg
import git
import github
import inquirer
import os
import typer

from pathlib import Path
from rich import print
from rich.console import Console
from typing import Optional

console = Console()
app = typer.Typer(help=
    """A CLI program for performing bulk operations on GitHub repositories.  Useful when managing student repositories in a classroom situation.  
        Requires, git and a GitHub user with an Access Token with the following scopes: repo, delete_repo, read:org."""
)

collabs_app = typer.Typer(help="Perform operations on repositories for which you are a collaborator")
app.add_typer(collabs_app, name="collabs")

config_app = typer.Typer(help="Configure cligh")
app.add_typer(config_app, name="config")

invitations_app = typer.Typer(help="Handle invitations in bulk")
app.add_typer(invitations_app, name="invitations")

repos_app = typer.Typer(help="Bulk repo operations for a specific user or organization")
app.add_typer(repos_app, name="repos")

STR_ALL_HELP = "Process all items after a single confirmation instead of confirming for each item individually"
STR_FILTER_RE_HELP = "Only repos with names that contain this regex will be included in the results"
STR_IS_ORG_HELP = "If this option is on, the NAME argument is assumed to be an organization; otherwise, a user is assumed"
STR_NAME_HELP = "The name of a GitHub user or organization"
STR_TARGET_HELP = "The path in which to operate"

def spinner(message):
    return console.status(message, spinner="point")

@config_app.command("set")
def config_set():
    """Set cligh configuration"""
    existing_cfg = cfg.get_all()
    new_cfg = prompt_config(existing_cfg)
    
    print(f"Saving conifuration to {cfg.CONFIG_FILE_PATH}")
    cfg.update(new_cfg)

@config_app.command("list")
def config_list():
    """List the current cligh configuration settings"""
    print(cfg.get_all())


def prompt_config(defaults=None):

    response_cfg = {}
    response_cfg['github_user'] = inquirer.text(message="What is your GitHub username?", default=defaults['github_user'] if defaults else ""),
    response_cfg['github_token'] = inquirer.text(message="What is your GitHub access token?"),
    response_cfg['github_username_file'] = inquirer.text(message="What name will you use for GitHub username files?", default=defaults['github_username_file'] if defaults else "")
    
    return response_cfg

def invitation_name(i):
    return "{}/{}".format(i['inviter']['login'], i['repository']['name'] if i['repository'] else "")

def repo_full_name(r):
    return r['full_name']

def repo_owner_name(r):
    return r['full_name'].split("/")[0]
def repo_name(r):
    return r['full_name'].split("/")[1]

def check_name(name, is_org):
    if is_org:
        with spinner("Verifying organization {name}"):
            name_exists = github.org_exists(name)
    else:
        with spinner("Verifying user {name}"):
            name_exists = github.user_exists(name)

    if not name_exists:
        if is_org:
            print(f"The organization {name} does not exist on GitHub.  If you are trying to list a user's repositories do NOT use the --org option.")
        else:
            print(f"The user {name} does not exist on GitHub.  If you are trying to list an organization's repositories use the --org option.")
        return False

    return True

@repos_app.command("list")
def list_repos(
    name : str = typer.Argument(..., help=STR_NAME_HELP),
    is_org : Optional[bool] = typer.Option(False, "--org", help=STR_IS_ORG_HELP), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """List all repositories for a GitHub user or organization"""

    if not check_name(name, is_org):
        return

    with spinner("Finding repos"):
        [ print(repo_full_name(r)) for r in github.get_repos(name, is_org, filter_re) ]

@repos_app.command("delete")
def delete_repos(
    name : str = typer.Argument(..., help=STR_NAME_HELP),
    is_org : Optional[bool] = typer.Option(False, "--org", help=STR_IS_ORG_HELP), 
    all : bool = typer.Option(False, help=STR_ALL_HELP),
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk delete repositories for a GitHub user or organization"""

    if not check_name(name, is_org):
        return

    with spinner("Finding repos"):
        repos = github.get_repos(name, is_org, filter_re)

    
    if ( len(repos) == 0 ):
        print("No repos to delete")
        return

    if ( all ):
        [ print(repo_full_name(r)) for r in repos ]

        print()
        print("[bold yellow]WARNING:[/bold yellow] You are about to [bold red]DELETE[/bold red] ALL {} of the above repositories."
            .format(len(repos)))
        if ( inquirer.confirm("Are you sure you wish to continue?") ):
            for r in repos:
                print("[bold red]DELETING[/bold red] {}...".format(repo_full_name(r)), end="", flush=True)
                github.delete_repo(repo_owner_name(r), repo_name(r))
                print("done")

    else: 
        for r in repos:

            if ( inquirer.confirm("Delete {}?".format(repo_full_name(r))) ) :
                print("[bold red]DELETING[/bold red] {}...".format(repo_full_name(r)), end="", flush=True)     
                github.delete_repo(repo_owner_name(r), repo_name(r))
                print("done")
            else:
                print("SKIPPED {}".format(repo_full_name(r)))

            print()


@repos_app.command("clone")
def clone_repos(
    name : str = typer.Argument(..., help=STR_NAME_HELP),
    into : Optional[Path] = typer.Argument(None, help="The name of the directory into which to clone the repo.  If this argument is specified, only one repository may be cloned. If it is not specified, multiple repos may be cloned into directories with the same names as the repos."),
    is_org : Optional[bool] = typer.Option(False, "--org", help=STR_IS_ORG_HELP), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk clone repos from a given user or organization"""

    if not check_name(name, is_org):
        return

    with spinner("Finding repos"):
        repos = github.get_repos(name, is_org, filter_re)

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

    for i in repo_idxs:
        git.clone(repos[i]['html_url'], into)
        
            
@app.command()
def batch_get(
    into : Path = typer.Argument(..., help="The name of the subfolder into which to clone/pull"), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """For each subdirectory of the current working directory that contains a GitHub username file (as determined by the github_username_file config setting), clone (or pull if already cloned) the repositories for that GitHub user."""

    subdirs = [ d for d in os.listdir() if os.path.isdir(d) ]

    for d in subdirs:

        subdir_target = os.path.join(d, into if into else "")

        p = os.path.join(d, cfg.get('github_username_file'))
        if ( os.path.exists(p) ):

            with open(p, 'r') as github_login_file:

                user = github_login_file.read().replace('\n', '')

                if user == '' :
                    print("[bold red]SKIPPING[/bold red] {} because the {} file was empty".format(d, cfg.get('github_username_file')))
                    continue

                with spinner(f"Verifying GitHub user {user}"):
                    if not github.user_exists(user):
                        print("[bold red]SKIPPING[/bold red] {} because no GitHub user {} exists".format(d, user))
                        continue

                if os.path.exists(subdir_target):
                    print("[bold green]PULLING[/bold green] ({} already exists)".format(subdir_target))
                    git.pull(subdir_target)
                    continue
                else:
                    print("[bold green]CLONING[/bold green] into {}...".format(subdir_target))
                    clone_repos(user, subdir_target, is_org=False, filter_re=filter_re)
        else:
            print("[bold red]SKIPPING[/bold red] {} because no {} file was found".format(d, cfg.get('github_username_file')))
            continue

@collabs_app.command("list")
def list_collabs(filter_re:Optional[str]= typer.Option(None, help=STR_FILTER_RE_HELP)):
    """List all repositories for which you are a collaborator"""

    with spinner("Finding collabs"):
        collabs = github.get_collabs(filter_re)

    [ print(repo_full_name(r)) for r in collabs ]

@collabs_app.command("leave")
def leave_collabs(
    all : bool = typer.Option(False, help=STR_ALL_HELP),
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk remove yourself as a collaborator from a set of repositories"""
    with spinner("Finding collabs"):
        repos = github.get_collabs(filter_re)

    if ( len(repos) == 0 ):
        print("No repos to leave")
        exit(0)

    if ( all ):
        [ print(repo_full_name(r)) for r in repos ]

        print()
        print("[bold yellow]WARNING:[/bold yellow] You are about to [bold red]LEAVE[/bold red] as a collaborator ALL {} of the above repositories."
            .format(len(repos)))
        if ( inquirer.confirm("Are you sure you wish to continue?") ):
            for r in repos:
                print("[bold red]LEAVING[/bold red] {}...".format(repo_full_name(r)), end="", flush=True)     
                github.leave_collab(r['owner']['login'], r['name'], cfg.get('github_user'))
                print("done")

    else: 
        for r in repos:

            if ( inquirer.confirm("Leave {}?".format(repo_full_name(r))) ) :
                print("[bold red]LEAVING[/bold red] {}...".format(repo_full_name(r)), end="", flush=True)     
                github.leave_collab(r['owner']['login'], r['name'], cfg.get('github_user'))
                print("done")
            else:
                print("SKIPPED {}".format(repo_full_name(r)))

            print()

@invitations_app.command("list")
def list_invitations(filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)):
    """List current pending invitations"""
    with spinner("Finding invitations"):
        invitations = github.get_invitations(filter_re)

    [ print(invitation_name(i)) for i in invitations ]

@invitations_app.command("accept")
def accept_invitations(
    all : Optional[bool] = typer.Option(False, help=STR_ALL_HELP), 
    filter_re : Optional[str] = typer.Option(None, help=STR_FILTER_RE_HELP)
):
    """Bulk accept invitations"""

    with spinner("Finding invitations"):
        invitations = github.get_invitations(filter_re)

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
                github.accept_invitation(i['id'])
                print("done")

    else: 
        for i in invitations:

            if ( inquirer.confirm("Accept {}?".format(invitation_name(i))) ) :
                print("[bold green]ACCEPTING[/bold green] {}...".format(invitation_name(i)), end="", flush=True)     
                github.accept_invitation(i['id'])
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
    
    with spinner("Finding invitations"):
        invitations = github.get_invitations(filter_re)

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
                github.decline_invitation(i['id'])
                print("done")

    else:

        for i in invitations:

            if ( inquirer.confirm("Decline {}?".format(invitation_name(i))) ) :
                print("[bold red]DECLINING[/bold red] {}...".format(invitation_name(i)), end="", flush=True)     
                github.decline_invitation(i['id'])
                print("done")

            else:
                print("SKIPPED {}".format(invitation_name(i)))

            print()

if __name__ == "__main__":
    if not cfg.is_initialized():
        print("This must be your first time running cligh!  Take a second to do some configuration...")
        new_cfg = prompt_config()
        cfg.update(new_cfg)
        
    cfg.load()

    github.set_api_token(cfg.get('github_token'))
    
    user = cfg.get('github_user')
    
    with spinner(f"Verifying GitHub user {user}"):
        user_exists = github.user_exists(user)
    
    if not user_exists:
        print("No GitHub user named '{}' exists".format(user))
    else:
        app()