from geogig.geogigwebapi.expression import ExpressionConverter


#from geogig.tests.ecqlTest import testECQL,verifyECQL
#testECQL()
def convertECQL(qgs_text_expr):
    converter = ExpressionConverter(text=qgs_text_expr)
    ecql =converter.asECQL()
    return ecql


def verifyECQL(qgs,ecqlExpected):
    ecql = convertECQL(qgs)
    if ecql != ecqlExpected:
        raise Exception("ecql - '{}' should have converted to '{}' but converted to '{}'".format(qgs,ecqlExpected,ecql))

def testECQL():
    verifyECQL("True","INCLUDE")
    verifyECQL("(True)","INCLUDE")
    verifyECQL("True AND True", "(INCLUDE AND INCLUDE)")
    verifyECQL("(True AND True)", "(INCLUDE AND INCLUDE)")
    verifyECQL("Column = 99", '("Column" = 99)')
    verifyECQL("TRUE AND Column = 99", '(INCLUDE AND ("Column" = 99))')
    verifyECQL("FALSE AND Column = 99", '(EXCLUDE AND ("Column" = 99))')
    verifyECQL("FALSE OR Column = 99", '(EXCLUDE OR ("Column" = 99))')
    verifyECQL("Column IN('trunk', 'motorway_link')", '("Column" IN (\'trunk\',\'motorway_link\'))')
    verifyECQL("Column = TRUE", '("Column" = True)')
    verifyECQL("(True AND True) AND Column = False", '((INCLUDE AND INCLUDE) AND ("Column" = False))')
    print("PASS")