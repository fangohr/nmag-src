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

"""
Module which allows to define in a high-level way the physics to be simulated
by the Nsim package.

nsim.model and SI units
-----------------------

The nsim.model module is completely independent from the SI object and the
nsim.si_units module, but at the same time the two modules can be used
together effectively. In this document we explain how this can be possible.
let's consider a SpaceField Quantity, for example. The user may want to set
it using an SI object. For example,

  M_sat.set_value(Value(0.86e6, SI("A/m"))

Obviously, the field data is just an array of floats, therefore one needs to
map the SI object to a float. This is done dependently on the units given in
the Quantity definition. For example, if the field was defined as:

  M_sat = SpaceField("M_sat", unit=SI(1e6, "A/m"))

Then the array of float representing the data for M_sat will be set uniformly
to the value 0.86 which is obtained doing

  float(set_value_arg/unit) (in this case, set_value_arg=0.86e6*SI("A/m"))

This construct is very generic and works in the case set_value_arg and
unit are two SI objects, but - more importantly - also when they are just
two floating point numbers. In the case of SI objects, what happens is that
if the value provided as argument to set_value (which we call set_value_arg)
has the right units, SI("A/m"), then the division will return an object of
type SI(1) which can be converted safely to a float. If the user provides
an SI object with different units, say SI("m"), then the division will give
rise to a dimensional SI object (SI("m^2/A")) which will induce the float
funciton to throw an exception. That is the way we get totally independent
from the SI object and the related stuff.
For example, the previous statements could be safely written as:

  M_sat = SpaceField("M_sat")
  M_sat.set_value(0.86e6)

In this case, unit is assumed to be simply 1.0, a floating point number.

Now let's see what happens when getting values from a Quantity.
For example, let's compute the average of the Quantity.

  v = M_sat.compute_average()

averages are returned as a Value objects. A Value object is composed by the
data (always non-dimensional: just floats) plus a factor. If you defined
M_sat as SpaceField(..., unit=SI(1e6, "A/m")), then the factor will be
SI(1e6, "A/m"). If you used SpaceField("M_sat"), then the prefactor will be
just 1.0. Notice that also M_sat.get_value() will return a Value object.
This does not imply a significant loss of performance, as the Value object
will be just a pair of the raw data (without any scaling, just as it is
represented internally) plus a multiplicative factor.

Notice that the Value object provides methods to convert it to floats
with the desired unit (see Value.change_unit).
"""

import sys, types, logging

import ocaml
import nmag
from nsim import linalg_machine as nlam

from computation import Computations, EqSimplifyContext, OpSimplifyContext, \
                        LAMProgram, Operator
from quantity import Quantities
from timestepper import Timesteppers
from nsim.snippets import contains_all

__all__ = ['Model', 'NsimModelError']

logger = logging.getLogger('nsim')

class NsimModelError(Exception):
    pass

#-----------------------------------------------------------------------------

def enumerated_list(z):
    return zip(range(len(z)),z)

def _extended_properties_by_region(region_materials, min_region=-1,
                                   extra_pbr=[]):
    """Internal: Generate properties_by_region"""
    pbr = {}

    def add_prop(region,prop):
        if pbr.has_key(region):
            pbr[region][prop] = True
        else:
            pbr[region] = {prop: True}

    # Ensure all the outer regions have the property "outer":
    for vac in range(min_region,0):
        add_prop(vac, "outer")

    for nr_region in range(len(region_materials)):
        add_prop(nr_region,str(nr_region))
        materials = region_materials[nr_region]
        for mat_name in materials:
            add_prop(nr_region, mat_name)
            add_prop(nr_region, "magnetic")
            add_prop(nr_region, "material")
            #for p in m.properties:
                #add_prop(nr_region,p)

    # Now that we initialized these hashes, map them back to lists:

    def sorted_keys(h):
        k=h.keys()
        k.sort()
        return k

    srk = sorted_keys(pbr)

    result = [(k, sorted_keys(pbr[k])) for k in srk]
    logger.info("properties_by_region: %s" % repr(result))
    return result

#-----------------------------------------------------------------------------

class Model(object):
    def __init__(self, name, mesh, mesh_unit, region_materials, min_region=-1,
                 properties_by_region=[]):
        # Just save the relevant stuff
        self.name = name
        self.mesh = mesh
        self.mesh_unit = mesh_unit
        self.dim = mesh.dim
        self.region_materials = region_materials
        self.min_region = min_region

        # Fill a map associating subfield name to region indices where
        # the subfield is defined.
        regions_of_subfield = {}
        for region_idx, subfield_names in enumerate(region_materials):
            for subfield_name in subfield_names:
                if regions_of_subfield.has_key(subfield_name):
                    region_idxs = regions_of_subfield[subfield_name]
                else:
                    regions_of_subfield[subfield_name] = region_idxs = []
                region_idxs.append(region_idx)
                # ^^^ we subtract one because we start from vacuum whose
                #     associated index is -1
        self.regions_of_subfield = regions_of_subfield

        # Things that get constructed when the object is "used"
        self.computations = Computations()
        self.quantities = Quantities()
        self.timesteppers = Timesteppers()

        # Initialise some members
        self.quantities.primary = None
        self.quantities.derived = None
        self.quantities.dependencies = None

        self.intensive_params = []

        self.all_material_names = [] # All different names of the materials

        self.elems_by_field = {}     # For each field: list of elems ordered
                                     # per region
        self.prototype_elems = []    # List of the prototype elements
        self.sibling_elems = {}
        self.properties_by_region = properties_by_region
        self.mwes = {}               # All the MWEs
        self.lam = None
        self._built = {}

    def _was_built(self, name):
        if self._built.has_key(name):
            return self._built.has_key(name)
        return False

    def add_quantity(self, quant):
        """Add the given quantity 'quant' to the current physical model.
        If 'quant' is a list, then add all the elements of the list, assuming
        they all are Quantity objects."""
        return self.quantities.add(quant)

    def add_computation(self, c):
        """Add the computation (Computation object) to the model."""
        return self.computations.add(c)

    def add_timestepper(self, ts):
        """Add the timestepper (Timestepper object) to the model."""
        return self.timesteppers.add(ts)

    def _build_elems_on_material(self, name, shape):
        # Build the 'all_materials' dictionary which maps a material name to
        # a corresponding element
        all_materials = {}
        for region in self.region_materials:
            for mat_name in region:
                logger.info("Processing material '%s'" % name)

                if not all_materials.has_key(mat_name):
                    elem_name = "%s_%s" % (name, mat_name)
                    elem = ocaml.make_element(elem_name, shape, self.dim, 1)
                    all_materials[mat_name] = (mat_name, elem)

        # Build a list of all the different names of the involved materials
        self.all_material_names = [all_materials[mn][0]
                                   for mn in all_materials]

        # Obtain a list fused_elem_by_region such that
        # fused_elem_by_region[idx] is the element obtained by fusing all the
        # elements corresponding to the materials defined in region idx.
        # fused_elem_by_region[idx] is then the right element for that region
        fused_elem_by_region = []
        for region in self.region_materials:
            # Build a list of the elements in the region
            elems_in_region = \
              map(lambda mat_name: all_materials[mat_name][1], region)
            # Fuse all these elements
            fused_elem = reduce(ocaml.fuse_elements, elems_in_region,
                                ocaml.empty_element)
            fused_elem_by_region.append(fused_elem)

        return fused_elem_by_region

    def _build_elems_everywhere(self, name, shape):
        elem = ocaml.make_element(name, shape, self.dim, 1)
        return map(lambda region: elem, self.region_materials)

    def _build_elems(self, name, shape, on_material=False):
        shape = list(shape)

        # Find whether we have built a similar field before, we may then use
        # it to build the new one
        for p_name, p_shape, p_elems, p_on_material in self.prototype_elems:
            if p_shape == shape and p_on_material == on_material:
                logger.info("Using element %s for field %s (sibling)"
                            % (p_name, name))
                self.sibling_elems[name] = p_name
                return p_elems

        if on_material:
            where = "on material"
        else:
            where = "everywhere"
        logger.info("Building element %s %s" % (name, where))

        if on_material:
            elems = self._build_elems_on_material(name, shape)

        else:
            elems = self._build_elems_everywhere(name, shape)

        self.prototype_elems.append((name, shape, elems, on_material))
        self.elems_by_field[name] = elems
        return elems

    def _build_mwe(self, name):
        if self.sibling_elems.has_key(name):
            p_name = self.sibling_elems[name] # prototype name
            assert not self.sibling_elems.has_key(p_name), \
                   "Cannot have sibling field of a sibling field."

            logger.info("Building MWE %s as sibling of %s" % (name, p_name))

            if self.mwes.has_key(p_name):
                p_mwe = self.mwes[p_name]
            else:
                p_mwe = self._build_mwe(p_name)

            rename_prefix = "%s/%s" % (name, p_name)
            q = self.quantities._by_name[name]
            if q.def_on_mat:
                all_material_names = self.all_material_names
                relabelling = \
                  map(lambda mn: ("%s_%s" % (p_name, mn),
                                  "%s_%s" % (name, mn)),
                      all_material_names)
            else:
                relabelling = [(p_name, name)]

            mwe = ocaml.mwe_sibling(p_mwe, name, rename_prefix, relabelling)
            self.mwes[name] = mwe
            return mwe

        logger.info("Building MWE %s" % name)
        elems = self.elems_by_field[name]
        mwe = ocaml.make_mwe(name, self.mesh.raw_mesh,
                             enumerated_list(elems), [], self.ext_pbr)
        self.mwes[name] = mwe
        return mwe

    def _build_operators(self):
        ops = self.computations._by_type.get('Operator', [])
        simplify_context = \
          OpSimplifyContext(quantities=self.quantities,
                            material=self.all_material_names)
        operator_dict = {}
        for op in ops:
            logger.info("Building operator %s" % op.name)
            op_text = op.get_text(context=simplify_context)
            mwe_in, mwe_out = op.get_inputs_and_outputs()
            op_full_name = op.get_full_name()
            assert len(mwe_in) == 1 and len(mwe_out) == 1, \
              ("Operators should only involve exactly one quantity as input "
               "and one quantity as output. However, for operator '%s' "
               "input=%s and output=%s." % (op.name, mwe_in, mwe_out))

            operator_dict[op_full_name] = \
              nlam.lam_operator(op_full_name, mwe_out[0], mwe_in[0], op_text)

            # We should now register a VM call to compute the equation
            logger.info("Creating operator program for %s" % op.name)
            v_in, v_out = ["v_%s" % name for name in mwe_in + mwe_out]
            op.add_commands(["SM*V", op_full_name, v_in, v_out])
            if op.cofield_to_field:
                op.add_commands(["CFBOX", mwe_out[0], v_out])

        self._built["Operator"] = True
        return operator_dict

    def _build_ksps(self):
        ksps = self.computations._by_type.get('KSP', [])

        ksp_dict = {}
        for ksp in ksps:
            ksp_full_name = ksp.get_full_name()
            ksp_dict[ksp_full_name] = \
              nlam.lam_ksp(ksp_full_name, ksp.operator.get_full_name(),
                           precond_name=ksp.precond_name,
                           ksp_type=ksp.ksp_type, pc_type=ksp.pc_type,
                           initial_guess_nonzero=ksp.initial_guess_nonzero,
                           rtol=ksp.rtol, atol=ksp.atol, dtol=ksp.dtol,
                           maxits=ksp.maxits,
                           nullspace_subfields=ksp.nullspace_subfields,
                           nullspace_has_constant=ksp.nullspace_has_constant)

        self._built["KSP"] = True
        return ksp_dict

    def _build_bems(self):
        bems = self.computations._by_type.get('BEM', [])

        bem_dict = {}
        for bem in bems:
            bem_full_name = bem.get_full_name()
            bem_dict[bem_full_name] = \
              nlam.lam_bem(bem_full_name, is_hlib=bem.is_hlib,
                           mwe_name=bem.mwe_name, dof_name=bem.dof_name,
                           boundary_spec=bem.boundary_spec,
                           lattice_info=bem.lattice_info,
                           matoptions=bem.matoptions,
                           hlib_params=bem.hlib_params)

        return bem_dict

    def _build_equations(self):
        eqs = self.computations._by_type.get('Equation', [])
        simplify_context = \
          EqSimplifyContext(quantities=self.quantities,
                            material=self.all_material_names)
        equation_dict = {}
        for eq in eqs:
            logger.info("Building equation %s" % eq.name)
            eq_text = eq.get_text(context=simplify_context)
            mwes_for_eq = eq.get_inouts()
            eq_full_name = eq.get_full_name()
            equation_dict[eq_full_name] = \
              nlam.lam_local(eq_full_name,
                             aux_args=self.intensive_params,
                             field_mwes=mwes_for_eq,
                             equation=eq_text)

            # We should now register a VM call to compute the equation
            logger.info("Creating equation program for %s" % eq.name)
            fields = ["v_%s" % name for name in eq.get_inouts()]
            eq.add_commands(["SITE-WISE-IPARAMS", eq_full_name, fields, []])

        self._built["Equations"] = True
        return equation_dict

    def _build_ccodes(self):
        ccodes = self.computations._by_type.get('CCode', [])
        #simplify_context = \
        #  EqSimplifyContext(quantities=self.quantities,
        #                    material=self.all_material_names)
        ccode_dict = {}
        for ccode in ccodes:
            logger.info("Building ccode %s" % ccode.name)
            ccode_full_name = ccode.get_full_name()
            ccode_dict[ccode_full_name] = ccode._build_lam_object(self)

            #eq_text = eq.get_text(context=simplify_context)
            #mwes_for_eq = eq.get_inouts()
            #eq_full_name = eq.get_full_name()
            #equation_dict[eq_full_name] = \
            #  nlam.lam_local(eq_full_name,
            #                 aux_args=self.intensive_params,
            #                 field_mwes=mwes_for_eq,
            #                 equation=eq_text)

            # We should now register a VM call to compute the equation
            logger.info("Creating ccode program for %s" % ccode.name)
            fields = ["v_%s" % name for name in ccode.get_inouts()]
            ccode.add_commands(["SITE-WISE-IPARAMS", ccode_full_name, fields, []])

        self._built["CCode"] = True
        return ccode_dict

    def _build_programs(self):
        progs = (self.computations._by_type.get('LAMProgram', [])
                 + self.computations._by_type.get('Equation', [])
                 + self.computations._by_type.get('Operator', []))
        prog_dict = {}
        for prog in progs:
            prog_name = prog.get_prog_name()
            logger.info("Building program %s" % prog_name)
            prog_dict[prog_name] = \
              nlam.lam_program(prog_name, commands=prog.commands)

        self._built["LAMPrograms"] = True
        return prog_dict

    def _depend(self, q1_name, q2_name):
        """Return whether the quantity q1_name depends on the quantity
        q2_name."""
        if q1_name in self.quantities.dependencies:
            op, input_qs = self.quantities.dependencies[q1_name]
            for input_q in input_qs:
                if input_q == q2_name:
                    return True
                elif self._depend(input_q, q2_name):
                    return True
        return False

    def _depend_path(self, q1_name, q2_name):
        """Return whether the quantity q1_name depends on the quantity
        q2_name."""
        if q1_name in self.quantities.dependencies:
            op, input_qs = self.quantities.dependencies[q1_name]
            for input_q in input_qs:
                if input_q == q2_name:
                    return "%s ==(%s)==> %s" % (q2_name, op.name, q1_name)
                else:
                    s = self._depend(input_q, q2_name)
                    if s:
                        return "%s ==(%s)==> %s" % (s, op.name, q1_name)
        return ""

    def _build_dependency_tree(self):
        # Determine dependencies and involved quantities
        q_dependencies = {}
        involved_qs = {}
        for computation in self.computations._all:
            if computation.auto_dep:
                # Compute automatically the dependencies
                inputs, outputs = computation.get_inputs_and_outputs()
                for o in outputs:
                    q_dependencies[o] = (computation, inputs)
                for q_name in inputs + outputs:
                    if not involved_qs.has_key(q_name):
                        involved_qs[q_name] = None

        # Determine primary quantities
        derived_qs = []
        primary_qs = []
        for q_name in involved_qs:
            if q_dependencies.has_key(q_name):
                derived_qs.append(q_name)
            else:
                primary_qs.append(q_name)

        self.quantities.primary = primary_qs
        self.quantities.derived = derived_qs
        self.quantities.dependencies = q_dependencies

        # Cecking for circular dependencies
        for derived_q in derived_qs:
            if self._depend(derived_q, derived_q):
                # does the quantity derived_q depend on itself
                dep_path = self._depend_path(derived_q, derived_q)
                raise NsimModelError("Circular dependency detected for %s: %s"
                                     % (derived_q, dep_path))

        self._built["DepTree"] = True

    def write_dependency_tree(self, out=sys.stdout):
        """Write to the provided stream (sys.stdout, if not provided)
        information about the inferred dependency tree between quantities
        and operators."""
        out.write("Primary quantities: %s\n" % self.quantities.primary)
        out.write("Derived quantities: %s\n" % self.quantities.derived)
        out.write("Dependencies (as INPUTS==[COMPUTATION]==>OUTPUT):\n")
        ds = self.quantities.dependencies
        for o in ds:
            c, i = ds[o]
            out.write("%s ==(%s)==> %s\n" % (i, c.name, o))

    def _build_target_maker(self, target, primaries={}, targets_to_make=[]):
        assert self._was_built("DepTree"), \
          "The target-maker builder can be used only after building the " \
          "dependency tree!"
        if not self.quantities.dependencies.has_key(target):
            primaries[target] = primaries.get(target, 0) + 1
        else:
            computation, inputs = self.quantities.dependencies[target]
            for i in inputs:
                self._build_target_maker(i, primaries, targets_to_make)
            targets_to_make.append(computation)

    def _build_timesteppers(self):
        nlam_tss = {}
        simplify_context = \
          EqSimplifyContext(quantities=self.quantities,
                            material=self.all_material_names)
        for ts in self.timesteppers._all:
            nr_primary_fields = len(ts.x)
            assert nr_primary_fields == len(ts.dxdt)

            inputs, outputs = \
              ts.eq_for_jacobian.get_inputs_and_outputs(context=simplify_context)

            all_names = inputs + outputs
            x_and_dxdt = ts.x + ts.dxdt
            if contains_all(all_names, x_and_dxdt):
                other_names = [name
                               for name in all_names
                               if name not in x_and_dxdt]

            else:
                eq = ts.eq_for_jacobian
                msg = ("Timestepper %s has x=%s and dxdt=%s, but does not "
                       "refer to one of them in the jacobian computed from "
                       "%s, which was simplified from: %s."
                       % (ts.name, ts.x, ts.dxdt,
                          eq.simplified_tree, eq.text))
                raise ValueError(msg)

            # List of all quantities involved in jacobi equation
            all_names = x_and_dxdt + other_names

            # Build a dictionary containing info about how to derive each
            # quantity
            how_to_derive = {}
            if ts.derivatives != None:
                for quant, way in ts.derivatives:
                    if isinstance(way, Operator):
                        op_full_name = way.get_full_name()
                        how_to_derive[quant.name] = ("OPERATOR", op_full_name)
                    else:
                        raise ValueError("Timestepper was build specifying "
                          "that %s should be used to compute the derivative "
                          "of %s, but only operators can be used at the "
                          "moment." % (quant.name, way.name))

            all_v_names = ["v_%s" % name for name in all_names]
            derivs = [("PRIMARY", "")]*(2*nr_primary_fields)
            for name in other_names:
                if how_to_derive.has_key(name):
                    derivs.append(how_to_derive[name])
                else:
                    derivs.append(("IGNORE", ""))

            # Build dxdt update program
            primaries = {}
            targets_to_make = []
            for dxdt in ts.dxdt:
                self._build_target_maker(dxdt, primaries, targets_to_make)
            if False:
                print "In order to update the RHS I have to:"
                for p in primaries:
                    print "distribute quantity %s" % p
                for t in targets_to_make:
                    print "run computation %s" % t.name
                raw_input()

            dxdt_updater = LAMProgram("TsUp_%s" % ts.name)
            for t in targets_to_make:
                dxdt_updater.add_commands(["GOSUB", t.get_prog_name()])

            self.computations.add(dxdt_updater)
            assert not self._was_built("LAMPrograms"), \
              "Timesteppers should be built before LAM programs!"

            full_name = ts.get_full_name()
            nlam_ts = \
              nlam.lam_timestepper(full_name,
                                   all_names,
                                   all_v_names,
                                   dxdt_updater.get_full_name(),
                                   nr_primary_fields=nr_primary_fields,
                                   name_jacobian=None,
                                   pc_rtol=ts.pc_rtol,
                                   pc_atol=ts.pc_atol,
                                   max_order=ts.max_order,
                                   krylov_max=ts.krylov_max,
                                   jacobi_eom=ts.eq_for_jacobian.get_text(),
                                   phys_field_derivs=derivs,
                                   jacobi_prealloc_diagonal=
                                     ts.jacobi_prealloc_diagonal,
                                   jacobi_prealloc_off_diagonal=
                                     ts.jacobi_prealloc_off_diagonal)

            nlam_tss[full_name] = nlam_ts
        self._built["TSs"] = True
        return nlam_tss

    def _build_lam(self):
        # Build LAM vector dictionary
        vectors = {}
        for mwe_name in self.mwes:
            vec_name = "v_%s" % mwe_name
            assert not vectors.has_key(vec_name), \
                   "Duplicate definition of vector '%s'" % vec_name
            quantity = self.quantities._by_name[mwe_name]
            vectors[vec_name] = \
              nlam.lam_vector(name=vec_name, mwe_name=mwe_name,
                              restriction=quantity.restrictions)

        operators = self._build_operators()
        bems = self._build_bems()
        ksps = self._build_ksps()
        equations = self._build_equations()
        ccodes = self._build_ccodes()
        jacobi = {} # Not used (should clean this)
        self._build_dependency_tree()
        timesteppers = self._build_timesteppers()
        programs = self._build_programs()
        debugfile = None

        lam = nlam.make_lam(self.name,
                            intensive_params=self.intensive_params,
                            mwes=self.mwes.values(),
                            vectors=vectors.values(),
                            operators=operators.values(),
                            bem_matrices=bems.values(),
                            ksps=ksps.values(),
                            local_operations=(equations.values()
                                              + ccodes.values()),
                            jacobi_plans=jacobi.values(),
                            programs=programs.values(),
                            timesteppers=timesteppers.values(),
                            lam_debugfile=debugfile)

        self.lam = lam

    def _vivify_objs(self, lam):
        logger.info("Vivifiying fields...")
        field_quants = (self.quantities._by_type.get('SpaceField', [])
                        + self.quantities._by_type.get('SpaceTimeField', []))
        for q in field_quants:
            q.vivify(self)

        logger.info("Vivifiying timesteppers...")
        for ts in self.timesteppers._all:
            ts.vivify(self)


    def build(self):
        # I'm keeping the same order of execution that we were using in the
        # old nmag_lam.py source
        field_quants = self.quantities._by_type.get('SpaceField', [])
        field_quants += self.quantities._by_type.get('SpaceTimeField', [])
        param_quants = self.quantities._by_type.get('TimeField', [])

        # Extended properties by region
        self.ext_pbr = \
          _extended_properties_by_region(self.region_materials,
                                         self.min_region,
                                         self.properties_by_region)

        # First build all the elements
        for field_quant in field_quants:
            self._build_elems(field_quant.name,
                              field_quant.shape,
                              on_material=field_quant.def_on_mat)

        # Now build all the MWEs
        for field_quant in field_quants:
            self._build_mwe(field_quant.name)

        self._build_lam()

        self._vivify_objs(self.lam)

        self._built["LAM"] = True


