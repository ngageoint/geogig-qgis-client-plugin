

COMMIT_NORMALIMPORTANCE = 0
COMMIT_IMPORTANT=1
COMMIT_UNIMPORTANT=2

class Commit:

    def __init__(self,repo_json,commitGraph):
        self.repo_json = repo_json
        self.commitGraph = commitGraph
        self.commitid = repo_json["id"]
        self.childrenIds = repo_json["childrenIds"]
        self.parentIds = repo_json["parentIds"]
        self.message = repo_json["message"]
        self.author = repo_json["author"]["name"]
        self.committer = repo_json["committer"]["name"]
        self.timestamp = repo_json["author"]["timestamp"]
        self.column = -1
        self.importance = COMMIT_NORMALIMPORTANCE

    def setImportance(self,importance):
        self.importance = importance

    def getImportance(self):
        return self.importance

    def isFork(self):
        ''' Returns True if the node is a fork'''
        return len(self.childrenIds) > 1

    def isMerge(self):
        ''' Returns True if the node is a fork'''
        return len(self.parentIds) > 1

    def getParents(self):
       return [self.commitGraph.getById(id) for id in self.parentIds]

    #sometimes parents are in the commitGraph (i.e. for a PR)
    # this will ignore them if we don't know about them
    def getParentsIfAvailable(self):
        return [self.commitGraph.getById(id) for id in self.parentIds if self.commitGraph.idPresent(id)]

    def getChildren(self):
       return [self.commitGraph.getById(id) for id in self.childrenIds]

    def getParent(self):
        return self.commitGraph.getById(self.parentIds[0])

    def hasParents(self):
        return len(self.parentIds) >0

    def numbParents(self):
        return len(self.parentIds)

class CommitGraph:

    def __init__(self,commitIdList,commitDetailsDic,importantCommitIds=None):
        self.commitIdList = commitIdList
        self.commitsById = {}

        for commit in commitDetailsDic.values():
            self.commitsById[commit["id"]] = Commit(commit,self)
        self.commits = [self.getById(id) for id in commitIdList]

        if importantCommitIds is not None:
            for c in self.commits:
                if c.commitid in importantCommitIds:
                    c.setImportance(COMMIT_IMPORTANT)
                else:
                    c.setImportance(COMMIT_UNIMPORTANT)

        self.importantCommitIds = importantCommitIds
        self.computeGraph()

    def idPresent(self,id):
        return id in self.commitsById

    def getById(self,id,default=None):
        return self.commitsById.get(id,None)

    # faux link is a line that doesn't have any commits on it (and will not draw in a simple graph)
    def isFauxLink(self,commit1,commit2):
        return (commit1,commit2) in self.faux

    def computeGraph(self):
        self.commitRows = {}
        self.commitColumns = {}
        self.faux = set()
        for i, commit in enumerate(self.commits):
            self.commitRows[commit.commitid] = i + 1
        used = []
        self.maxCol = 0

        def addCommit(commit, col):
            used.append(commit.commitid)
            self.commitColumns[commit.commitid] = col
            try:
                for i, parent in enumerate(commit.getParents()):
                    if parent.commitid not in used:
                        if i == 0:
                            nextCol = col
                        else:
                            self.maxCol = self.maxCol + 1
                            nextCol = self.maxCol
                        addCommit(parent, nextCol)
                    else:
                        if commit.numbParents() > 1:
                            self.faux.add( (commit.getParents()[1].commitid,commit.commitid) )
            except:
                pass

        if self.commits:
            addCommit(self.commits[0], 0)

        for id, col in self.commitColumns.items():
            self.getById(id).column = col


        # FIXUP columns.  As of now, each section has its own column number.
        # But, we need to collapse that somewhat - or it will be too wide
        #  We go through each of the columns
        #     We figure out what commits are associated with that column (thats from branch to merge -- not just the ones encoded with that column number)
        #     We then check to see what columns are in that range
        #     If there's an unused column, we move it to that one
        #
        # Its complicated just because we are using a lot of bookkeeping
        #  commits - list of all commits
        #  commitColumns -- from simple algo (above), this is encodes each commit with a SINGLE column #
        #  commitCols2   -- each commit is associated with a SET of columns that are in-use for that commit (they will have a line in the end result)

        # each commit will have all the column#s that would have a line there
        self.commitCols2 = {}
        self.encodeColumns()

        # walk through each column and see if you can place it earlier
        for i in range(2, self.maxCol+1):
            commits = self.findAllRowsUsedByColumn(i)
            cols = self.columnUsedbyCommits(commits)
            freecolumn = self.missingNumber(cols)
            if freecolumn != -1 and freecolumn < i:
                self.relabel(i,freecolumn)
                self.encodeColumns() # recalculate everything


    # populates self.commitCols2
    # self.commitCols2[commitid] = list of columns that are active there (i.e. will draw a line)
    def encodeColumns(self):
        for i in range(0, self.maxCol+1):
            commits = self.findAllRowsUsedByColumn(i)
            for commit in commits:
                l = self.commitCols2.get(commit,[])
                l.append(i)
                self.commitCols2[commit] = l

    # finds the first (branch) and last (merge) for a column number
    #  The final graph will have a line running from first to last, where
    #  the result of this will be all those commitids
    def findAllRowsUsedByColumn(self,columnNumb):
        # find the first and last commit that have the column number
        #   (these are exclusive-to-that-column commits)
        firstCommit = None
        lastCommit = None
        for commit in self.commits:
            if commit.column == columnNumb:
                lastCommit = commit.commitid
                if firstCommit is None:
                    firstCommit = commit.commitid

        if lastCommit is None:
            return []

        # line actually goes from parent to child
        if self.commitsById[lastCommit].hasParents() and self.commitsById[lastCommit].getParent() is not None:
            idEnd = self.commitsById[lastCommit].getParent().commitid
        else:
            idEnd = lastCommit # first item in history

        if self.findCommitWithParent(firstCommit) is not None:
            idStart = self.findCommitWithParent(firstCommit).commitid
        else:
            idStart = firstCommit

        result =[]
        inside = False
        for commit in self.commits:
            if idStart==commit.commitid:
                inside = True
            if inside:
                result.append(commit.commitid)
            if idEnd==commit.commitid:
                return result
        pass


    # move a column from one place to another
    # update self.commits[..].column
    # update self.commitCols2 (note - recalculated later)
    # update self.commitColumns
    def relabel(self,oldColumn,newColumn):
        for commit in self.commits:
            if commit.column == oldColumn:
                commit.column = newColumn
        for id,ls in self.commitCols2.items():
            if oldColumn in ls:
                ls.remove(oldColumn)
                self.commitCols2[id] =ls
        for id, col in self.commitColumns.items():
            if col == oldColumn:
                self.commitColumns[id] = newColumn

    # (1,2,  4, ,6) --> 3
    # -1 means none missing
    def missingNumber(self,numbs):
        maxNumb =  max(numbs)
        for n in range(1,maxNumb):
            if n not in numbs:
                return n
        return -1

    # find the merge commit for a commit (i.e. a commit that has this commit as a parent)
    def findCommitWithParent(self,id):
        for commit in self.commits:
            if commit.numbParents() >1:
                parents = commit.getParentsIfAvailable()
                for parent in parents:
                    if parent.commitid == id:
                        return commit

    # walk the list of commits and find all the columns that those
    # commits reference.  Return unique list of those
    def columnUsedbyCommits(self,commitids):
        result = set()
        for commitid in commitids:
            cols = self.commitCols2[commitid]
            for c in cols:
                result.add(c)
        return sorted(list(result))





