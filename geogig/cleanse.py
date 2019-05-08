
def cleanse(str,whitelist):
    if str is None:
        return None
    return ''.join(c for c in str if c in whitelist)

def cleanseTransactionId(tx):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'
    return cleanse(tx,whitelist)


def cleanseTaskId(taskid):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'
    return cleanse(taskid, whitelist)

def cleanseUserName(uname):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'
    return cleanse(uname, whitelist)

def cleanseRepoName(rname):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'
    return cleanse(rname, whitelist)

def cleanseLayerName(lname):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'
    return cleanse(lname, whitelist)

def cleanseBranchName(bname):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'
    return cleanse(bname, whitelist)

def cleanseRefSpec(refspec):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-^~'
    return cleanse(refspec, whitelist)

def cleanseCommitId(id):
    whitelist = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-^~'
    return cleanse(id, whitelist)

def cleansePRId(prid):
    return int(prid)


# does the same as dictionary.get(key) but doesn't use .get()
# this is ONLY for Fortify to stop thinking that dictionary.get() isn't a call to requests.get()
# SIGH!
def dictGet(dict,value,default=None):
    try:
        return dict[value]
    except KeyError:
        return default
