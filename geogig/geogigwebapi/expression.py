from qgis._core import QgsExpression, QgsExpressionNodeBinaryOperator, QgsExpressionNodeLiteral, \
    QgsExpressionNodeColumnRef, QgsExpressionNodeInOperator, QgsExpressionNodeUnaryOperator


class ExpressionConverter:
    unaryNodeType = {
        0: " NOT ",
        1: " -"
    }

    binaryNodeType = {
        1: "AND",
        2: "=",
        5: ">=",
        7: ">",
        11: "ILIKE",
        13: "IS",
        14: "IS NOT",
        4: "<=",
        9: "LIKE",
        6: "<",
        3: "<>",
        12: "NOT ILIKE",
        10: "NOT LIKE",
        0: "OR",
        16: "-",
        17: "*",
        15: "+",
        18: "/"
    }

    # call with either text=<expression text> or expression=QgsExpression()
    def __init__(self, text=None, expression=None):
        if expression is None:
            expression = QgsExpression(text)
        self.expression = expression
        self.expressionText = expression.dump()

        self.needsGeometry = expression.needsGeometry()
        self.colNames = expression.referencedColumns()  # should be checked against layer.fields()
        self.referencedFunctions = expression.referencedFunctions()

        if self.needsGeometry:
            raise Exception("cannot translate expression with geometry")
        if self.referencedFunctions:
            raise Exception("cannot translate expression with functions")

    # http://docs.geoserver.org/latest/en/user/filter/ecql_reference.html
    def asECQL(self):
        return self.parse(self.expression.rootNode(),mustReturnTruth=True)

    def parse(self, node,mustReturnTruth=False):
        if isinstance(node, QgsExpressionNodeBinaryOperator):
            return self.parseBinary(node,mustReturnTruth)
        elif isinstance(node, QgsExpressionNodeLiteral):
            return self.parseLiteral(node,mustReturnTruth)
        elif isinstance(node, QgsExpressionNodeColumnRef):
            return self.parseColumnRef(node)
        elif isinstance(node, QgsExpressionNodeInOperator):
            return self.parseIn(node)
        elif isinstance(node, QgsExpressionNodeUnaryOperator,):
            return self.parseUnary(node,mustReturnTruth)
        raise Exception("cannot parse expression- " + str(node) + "=> " + node.dump())

    def parseBinary(self, node,mustReturnTruth=False):
        op = node.op()
        # hidden check -- will throw exeception if we don't know what the op is
        # (i.e. || concat)
        op_text = self.binaryNodeType[op]
        mustReturnTruth = mustReturnTruth and (op == 1 or op == 0)
        right = self.parse(node.opRight(),mustReturnTruth=mustReturnTruth)
        left = self.parse(node.opLeft(),mustReturnTruth=mustReturnTruth)
        return "(" + left + " " + op_text + " " + right + ")"  # be very explicit about order-of-ops

    def parseUnary(self, node,mustReturnTruth=False):
        op = node.op()
        op_text = self.unaryNodeType[op]  # there are, currently, only 2 unary ops defined
        opperand = self.parse(node.operand(),mustReturnTruth=True)
        return "(" + op_text + opperand + ")"  # be very explicit about order-of-ops

    def parseLiteral(self, node,mustReturnTruth=False):
        val = node.value()
        if val is None:
            return "NULL"
        if mustReturnTruth and isinstance(val,bool):
            return "INCLUDE" if val else "EXCLUDE"
        if isinstance(val, str):
            val = val.replace("'", "''")  # handle ' in text (ecql spec)
            return "'" + str(val) + "'"
        if isinstance(val, int):
            return str(val)
        if isinstance(val, float):
            return repr(val)
        # likely one of the types we don't handle
        raise Exception("cannot parse expression- " + str(val) + "=> " + type(val))

    def parseColumnRef(self, node):
        return '"' + node.name() + '"'  # "varname" is the ecql spec for being explicit about names

    def parseIn(self, node):
        items = node.list().list()
        # we assume they are literals
        vals = [self.parseLiteral(item) for item in items]
        left = self.parse(node.node())  # this should be a col ref
        op = " IN "
        if node.isNotIn():
            op = " NOT IN "
        return "(" + left + op + "(" + ",".join(vals) + ")" + ")"  # explict order of ops
