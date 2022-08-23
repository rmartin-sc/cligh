#!/usr/bin/env bash
complete -W "batch-clone collabs config invitations user" cligh
complete -W "leave" cligh collabs
complete -W "accept decline" cligh invitations
complete -W "repos" cligh user
complete -W "clone" cligh user repos
