import re
import requests

V4_API_BASE = "https://api.github.com/graphql"
V3_API_BASE = "https://api.github.com"

v4headers = {}
v3headers = {
    "Accept" : "application/vnd.github.v3+json"
}

def set_api_token(token):
    v3headers['Authorization'] = "bearer " + token
    v4headers['Authorization'] = "bearer " + token


def compile_re(re_str):
    return re.compile(re_str, re.IGNORECASE) if re_str else None


def query(q):
    return { "query" : " { " + q + " rateLimit { limit cost remaining resetAt } } " }

def exit_on_bad_response(response):
    if response.status_code >= 400:
        print("{}\n{}".format(response.status_code, response.text))
        exit(1)

def v3Url(q):
    return f"{V3_API_BASE}{q}"


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
    
    response = v4request("user(login: \"{}\") {{ login }}".format(name))

    if ( 'errors' in response ):
        return False
    
    return True

def org_exists(name):
    response = v4request("organization(login: \"{}\") {{ login }}".format(name))

    if ( 'errors' in response ):
        return False
    
    return True


def get_collabs(filter_re=None):
    repos = v3request_all_pages("/user/repos", {"affiliation": "collaborator"})

    if ( filter_re ):
        filter_re = compile_re(filter_re)
        return [ r for r in repos if filter_re.search(r['full_name']) ]

    return repos

def leave_collab(owner_login, repo_name, leaving_user_login):
    response = requests.delete(v3Url(f"/repos/{owner_login}/{repo_name}/collaborators/{leaving_user_login}"), headers=v3headers)
    exit_on_bad_response(response)

def get_invitations(filter_re=None):

    invitations = v3request_all_pages("/user/repository_invitations")
    
    if ( filter_re ): 
        filter_re = compile_re(filter_re)
        return [ i for i in invitations if (filter_re.search(i['repository']['full_name']) if i['repository'] else False) ]
    else:
        return [ i for i in invitations if i['repository'] ]

def accept_invitation(invitation_id):
    response = requests.patch(v3Url("/user/repository_invitations/{}".format(invitation_id)), headers=v3headers)
    exit_on_bad_response(response)

def decline_invitation(invitation_id):
    response = requests.delete(v3Url("/user/repository_invitations/{}".format(invitation_id)), headers=v3headers)    
    exit_on_bad_response(response)


def get_repos(name, is_org, filter_re=None):

    entity = "organization" if is_org else "user"


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

def delete_repo(owner_name, repo_name):
    response = requests.delete(v3Url(f"/repos/{owner_name}/{repo_name}"), headers=v3headers)
    exit_on_bad_response(response)