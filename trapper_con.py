from io import BytesIO
import requests
from requests.compat import urljoin as urlj
from pandas import read_csv


class TrapperConnection:
    """
    TODO: docstrings
    """

    # these urls can change in the future as the software is
    # under active development
    URLS = {
        "LOGIN": "/accounts/api/users/login/",
        "DEPLOYMENTS": "/geomap/api/deployments/export/",
        "RESULTS": "/media_classification/api/classifications/results/{cp}/",
        "RPROJECTS": "/research/api/projects",
        "PROCESS_COLLECTION": "/storage/api/collection/process/",
    }

    def __init__(self, host):
        self.host = host
        self.login_url = urlj(self.host, self.URLS["LOGIN"])
        self.login_correct = False
        self._login = None
        self.username = None
        self.password = None
        self.verify = None

    def test_login(self, _login, password, verify=True):
        """ """
        self._login = _login
        self.password = password
        self.verify = verify
        login_data = {
            "email": self._login,
            "password": self.password,
        }
        r = requests.post(self.login_url, data=login_data, verify=verify)
        r = r.json()
        error_code = r.get("error", None)
        username = r.get("username", None)
        if error_code == "0":
            self.login_correct = True
            self.username = username
        else:
            self.login_correct = False
        return error_code

    def get_deployments(self, query_str=None, save_csv=False):
        """ """
        api_url = urlj(self.host, self.URLS["DEPLOYMENTS"])
        if query_str:
            api_url = urlj(api_url, query_str)
        r = requests.get(api_url, auth=(self._login, self.password), verify=self.verify)
        df = read_csv(BytesIO(r.content))
        if save_csv:
            df.to_csv("deployments.csv")
        return df

    def get_cp_results(self, cproject, query_str=None, save_csv=False):
        """ """
        api_url = urlj(self.host, self.URLS["RESULTS"].format(cp=str(cproject)))
        if query_str:
            api_url = urlj(api_url, query_str)
        r = requests.get(api_url, auth=(self._login, self.password), verify=self.verify)
        df = read_csv(BytesIO(r.content))
        if save_csv:
            df.to_csv("results.csv")
        return df

    def get_rprojects(self, query_str="", psize=100, roles=["Admin", "Collaborator"]):
        """ """
        api_url = urlj(self.host, self.URLS["RPROJECTS"])
        api_url = "?".join([api_url, query_str])
        api_url = "&".join([api_url, "psize={}".format(psize)])
        r = requests.get(api_url, auth=(self._login, self.password), verify=self.verify)
        r = r.json().get("results", None)
        if r and roles:
            r_filtered = []
            for rp in r:
                rp_roles = rp["project_roles"]
                for rp_role in rp_roles:
                    if rp_role["username"] == self.username:
                        for role in roles:
                            if role in rp_role["roles"]:
                                r_filtered.append(rp)
            return r_filtered
        return r

    def collection_process(self, data):
        """ """
        api_url = urlj(self.host, self.URLS["PROCESS_COLLECTION"])
        r = requests.post(
            api_url, data=data, auth=(self._login, self.password), verify=self.verify
        )
        return r
