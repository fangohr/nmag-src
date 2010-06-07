# Nmag micromagnetic simulator
# Copyright (C) 2010 University of Southampton
# Hans Fangohr, Thomas Fischbacher, Matteo Franchin and others
#
# WEB:     http://nmag.soton.ac.uk
# CONTACT: nmag@soton.ac.uk
#
# AUTHOR(S) OF THIS FILE: Matteo Franchin
# LICENSE: GNU General Public License 2.0
#          (see <http://www.gnu.org/licenses/>)

"""Provides a function to parse an operator string and return a tree
representation of the operator which can be used to simplify it,
examine the quantities involved and finally rewrite it as text."""

__all__ = ['OperatorNode', 'ContribsNode', 'ContribNode', 'UContribNode',
           'BraKetNode', 'SignSym']

from tree import *

class SignSym(GenericSym):
    def __str__(self):
        v = self.value
        if v == 1.0:
            return "+"
        elif v == -1.0:
            return "-"
        else:
            assert v == None
            return ""

Node = GenericNode

class OperatorNode(Node):
    fmt = minimal_list_formatter

    def __init__(self, children=[], data=[],
                 contribs=None, amendments=None, sums=None):
        children.extend(filter(None, [contribs, amendments, sums]))
        Node.__init__(self, children=children, data=data)

class ContribsNode(AssocNode):
    pass

class ContribNode(Node):
    pass

class UContribNode(AssocNode):
    fmt = minimal_list_formatter

    def __init__(self, children=[], data=[], prefactor=1.0):
        if prefactor:
            data = [prefactor]
        Node.__init__(self, children=children, data=data)

class BraKetNode(Node):
    fmt = ListFormatter("<", ">", "|")
