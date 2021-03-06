"""This module contains a tools to export the nmesh meshes for other applications.

   magpar_ucd(mesh)

   
   Author: Richard P Boardman, Hans Fangohr   Last modified: $Date$

   Warning: This is reversed engineered and poorly tested.

   Filename: export.py

   Todo:
     - avoid opening and closing file all the time
     - convert print into log statements
     - test writing triangles
     
   Version: $Id$
"""
from __future__ import division

import time,os

from nmesh_exceptions import *

import nbase
log = nbase.logging.getLogger('nmesh')

def magpar_ucd(mesh,output_filename):
    


    def bail(message):
        print "Sorry, I don't understand. Bailing out..."
        print message
        sys.exit(1)

    def initialise_file(message, file):
        """Attept to remove the file first to avoid append issues"""
        if os.path.exists(file):
            os.remove(file)
            

        ###########################
        ### note: we need to leave this out
        ### as extraneous comments seem to cause problems when
        ### the meshes are read by magpar

        #f = open(file, 'w')
        #f.write(message + "\n")
        #f.close()
        ###########################    

    def write_line_to_file(line, file):
        """One-shot file line append; this keeps the code tidy (not very efficient though)"""
        f = open(file, 'a')
        f.write(line + "\n")
        f.close()

    def tad():
        """Format a time and date string for stdout information"""
        t = time.localtime()
        return "[%04d-%02d-%02d %02d:%02d:%02d] " % (t[0], t[1], t[2], t[3], t[4], t[5])

    def convert_strlist_to_intlist(strlist):
        intlist = []
        for item in strlist:
            intlist.append(int(item))
        return intlist

    #Here the work starts

    print "and then create an AVS-compliant mesh called " + output_filename
    print

    print tad() + "Initialising file " + output_filename

    initialise_file("# generated by ng2ucd, " + tad(), output_filename)

    print tad() + "File " + output_filename + " initialised successfully"

    points = mesh.points

    assert len(points)>0,"Need at least one point (probably a few more would be better)"
    if len(points[0]) != 3:
        raise NmeshUserError,"Magpar can only deal with three dimensional meshes"
    
    tetras = mesh.simplices
    tetrasregions=mesh.simplicesregions
    triangles=mesh.surfaces
    trianglesregions=mesh.surfacesregions

    print tad() + "Input mesh successfully read"

    ### pop out some information about the mesh

    print tad() + "Points:", len(points)
    print tad() + "Tetrahedra:", len(tetras)
    print tad() + "Triangles:", len(triangles)

    # first line of a UCD file goes something like
    # a b c d e
    # where a is the number of nodes
    #       b is the number of cells
    #       c is the length of vector data associated with the nodes
    #       d is the length of vector data associated with the cells
    #       e is the length of vector data associated with the model
    # example: 12 2 1 0 0

    print tad() + "Creating numeric UCD descriptor"
    write_line_to_file( str(len(points)) + " " +
                        str(len(tetras)) + " 13 0 0",
                        output_filename) # removed tri for test
    print tad() + "Numeric UCD descriptor created"

    # then we have the nodes, one line per node
    # n x y z
    # where n is the node ID --- an integer (not necessarily sequential)
    #       x is the x coordinate
    #       y is the y coordinate
    #       z is the z coordinate

    print tad() + "Converting nodes..."
    for i in range(len(points)):
        write_line_to_file( str(i+1) + " " +
                            str(points[i][0]) + " " +
                            str(points[i][1]) + " " +
                            str(points[i][2]),
                            output_filename)
    print tad() + "Nodes converted"

    # then we have the cells, one line per cell
    # c m t n1 n2 n3 ... nn
    # where c is the cell ID
    #       m is the material type (integer, can leave as 1 if we don't care)
    #       t is the cell type (prism, hex, pyr, tet, quad, tri, line, pt)
    #       n1 ... nn is a list of the node IDs which are the vertices of the cell

    cell_counter = 0

    print tad() + "Converting tetrahedra..."

    ### here we need to be careful of the order
    ### in which we write the tetrahedra points
    ### to avoid "negative" volume issues

    for i in range(len(tetras)):
        tet = tetras[i]

        ts = ""
        tetorder = [0, 2, 1, 3]

        ts = " " + str(tet[tetorder[0]]+1) + " " + str(tet[tetorder[1]]+1) + " " + str(tet[tetorder[2]]+1) + " " + str(tet[tetorder[3]]+1)
        write_line_to_file( str(cell_counter + 1) + " " + str(tetrasregions[i]) + " tet" + ts, output_filename)
        cell_counter = cell_counter + 1

    print tad() + "Tetrahedra converted"

    #############################################
    ####
    ####  Uncomment the following section to
    ####  convert triangles as well
    ####  note: magpar will ignore triangles,
    ####  so we leave this away for now

    ## note: triangle section untested for pyfem (only tested for netgen neutral)

    ##    print tad() + "Converting triangles..."

    ##    for i in range(len(triangles)):
    ##        tri = triangles[i]
    ##        ts = ""
    ##        for node in tri:
    ##            ts = ts + " " + str(node+1)
    ##        write_line_to_file( str(cell_counter + 1) + " "+str(trianglesregions[i])+" tri" + ts, output_filename)
    ##        cell_counter = cell_counter + 1

    ##    print tad() + "Triangles converted"

    #############################################


    # for the data vector associated with the nodes:
    # first line tells us into which components the vector is divided
    # example: vector of 5 floats could be 3 3 1 1
    # node scalar could be as 1 1
    # next lines, for each data component, use a cs label/unit pair
    # example: temperature, kelvin
    # subsequent lines, for each node, the vector of associated data in this order
    # example: 1 10\n2 15\n3 12.4\n4 9

    print tad() + "Initialising placeholders..."

    write_line_to_file("13 1 1 1 1 1 1 1 1 1 1 1 1 1", output_filename)
    write_line_to_file("M_x, none", output_filename)
    write_line_to_file("M_y, none", output_filename)
    write_line_to_file("M_z, none", output_filename)
    write_line_to_file("divM, none", output_filename)
    write_line_to_file("u1, none", output_filename)
    write_line_to_file("u2, none", output_filename)
    write_line_to_file("u, none", output_filename)
    write_line_to_file("Hdemag_x, none", output_filename)
    write_line_to_file("Hdemag_y, none", output_filename)
    write_line_to_file("Hdemag_z, none", output_filename)
    write_line_to_file("Hexchani_x, none", output_filename)
    write_line_to_file("Hexchani_y, none", output_filename)
    write_line_to_file("Hexchani_z, none", output_filename)

    # create some initial scalar values; here, generally
    # +x=1.0 +y=+z=0.01*x (everything else)="\epsilon"

    for i in range(len(points)):
        write_line_to_file( str(i+1) + " 1.0 0.01 0.01 1e-5 1e-5 1e-5 1e-5 1e-5 1e-5 1e-5 1e-5 1e-5 1e-5", output_filename)

    print tad() + "Placeholders inserted"

    # all done

    print tad() + "All finished."

