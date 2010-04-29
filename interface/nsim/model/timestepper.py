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

__all__ = ['Timestepper', 'Timesteppers']

from group import Group

class Timestepper:
    type_str = "SundialsCVode"

    def __init__(self, name, x, dxdt,
                 eq_for_jacobian=None):
        """
        Timestepper parameters:
            pc_rtol=None, pc_atol=None,
            max_order=2,
            krylov_max=None
        RHS:
            RHS='update_dmdt'
        Jacobi parameters:
            name_jacobian=None, # XXX TO BE OBSOLETED!
            jacobi_prealloc_diagonal=75,
            jacobi_prealloc_off_diagonal=45
        Parameters for computation of Jacobian:
            jacobi_eom=eq_rhs_jacobi_ts1,
            phys_field_derivs=[("PRIMARY",""),
                            ("PRIMARY",""),
                            ("OPERATOR","op_H_exch"),
                            ("IGNORE",""),
                            ("IGNORE","")],
            ['m','dmdt','H_total','H_anis','pin'], #check auxiliary fields for Jacobian are right
            ['v_m','v_dmdt','v_H_total','v_H_anis','v_pin'],
            nr_primary_fields=1,
        """
        self.name = name

class Timesteppers(Group):
    pass