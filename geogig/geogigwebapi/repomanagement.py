from qgis.PyQt.QtCore import *
from geogig.geogigwebapi.connector import GeogigError
from geogig.cleanse import *

class Repo(object):

    def __init__(self, jsonRepo, server):
        self.repoName = jsonRepo["identity"]
        self.repoId = jsonRepo["id"]
        self.ownerName = jsonRepo["owner"]["identity"]
        self.ownerId = jsonRepo["owner"]["id"]
        self.forkedFrom = jsonRepo["forked_from"]
        self.type  = "real"
        self.children = []
        self.underlyingJson = jsonRepo
        self.server = server

    def __str__(self):
        return str(self.__dict__)

    def __eq__(self, o):
        return self.repoName == o.repoName and self.ownerName == o.ownerName

    def fullName(self):
        return Repo.fullNameFromUserAndName(self.ownerName, self.repoName)

    @staticmethod
    def fullNameFromUserAndName(user, name):
        return user + ":" + name

    def forkRepo(self, forkName):
        return self.server.forkRepo(self.ownerName, self.repoName, forkName)

    def delete(self):
        return self.server.deleteRepo(self.ownerName, self.repoName)

class Constellation(QObject):

    def __init__(self, repos, originalRepo):
        QObject.__init__(self)
        self.all = repos
        self.repo = originalRepo
        self.root = self.repo
        while self.root.forkedFrom is not None:
            self.root = self.root.forkedFrom

class RepoManagement():

    def repo(self, user, repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        return self.connector.getHttp("repos/{}/{}".format(user, repo))

    def createRepo(self, user, repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        repos = self.reposForUser(user)
        if repo in [r["identity"] for r in repos]:
            raise GeogigError("A repository with that name already exists for the specified user") 
        self.connector.post("repos/{}/{}".format(user, repo),json={})
        self.repoCreated.emit(user, repo)

    def deleteRepo(self, user, repo):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        self.connector.delete("repos/{}/{}".format(user, repo))
        self.repoDeleted.emit(user, repo)       

    def forkRepo(self, user, repo, name):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        name = cleanseRepoName(name)

        repos = self.reposForUser(self.connector.user)
        if name in [r["identity"] for r in repos]:
            raise GeogigError("A repository with that name already exists for the current user")                
        query = {"forkName": name}
        taskId = self.connector.post("repos/{}/{}/forks".format(user, repo), params=query)["id"]
        self.waitForTask(taskId, "Forking repository")
        self.repoForked.emit(user, repo, name)
        
    def parentRepo(self, user, repo, fullInfo=False):
        user = cleanseUserName(user)
        repo = cleanseRepoName(repo)
        repoInfo = self.connector.getHttp("repos/{}/{}".format(user, repo))
        try:
            if fullInfo:
                return repoInfo
            else:
                return (repoInfo["forked_from"]["owner"]["identity"], repoInfo["forked_from"]["identity"])
        except:
            return None, None

    def constellation(self, user, repoName):
        user = cleanseUserName(user)
        repoName = cleanseRepoName(repoName)
        const = self.connector.getHttp("repos/{}/{}/constellation".format(user, repoName))
        reposByFullName = {}
        for jsonRepo in const:
            repo = Repo(jsonRepo, self)
            reposByFullName[repo.fullName()] = repo
        # replace fork with reference to fork
        for repo in reposByFullName.values():
            repo.forkedFrom = None
            if repo.underlyingJson["forked_from"] is not None:
                jsonForkInfo = repo.underlyingJson["forked_from"]
                parentName = jsonForkInfo["owner"]["identity"] + ":" + jsonForkInfo["identity"]
                if parentName in reposByFullName: # if false, parent was deleted
                    repo.forkedFrom = reposByFullName[parentName]
                    repo.forkedFrom.children.append(repo)

        return Constellation(reposByFullName.values(), reposByFullName[Repo.fullNameFromUserAndName(user, repoName)])

    def reposForUser(self, user):
        user = cleanseUserName(user)
        return self.connector.getHttp("repos/{}".format(user))