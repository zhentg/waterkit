#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# WaterKit
#
# Launch waterkit
#

import os
import imp
import argparse

from waterkit import AutoDockForceField
from waterkit import Map
from waterkit import Molecule
from waterkit import WaterKit


def cmd_lineparser():
    parser = argparse.ArgumentParser(description="waterkit")
    parser.add_argument("-i", "--mol", dest="mol_file", required=True,
                        action="store", help="receptor file")
    parser.add_argument("-m", "--fld", dest="fld_file", required=True,
                        action="store", help="autodock fld file")
    parser.add_argument("-l", "--layer", dest="n_layer", default=0, type=int,
                        action="store", help="number of layer to add")
    parser.add_argument("-t", "--temperature", dest="temperature", default=300., type=float,
                        action="store", help="temperature")
    parser.add_argument("-c", "--choice", dest="how", default="boltzmann",
                        choices=["best", "boltzmann"], action="store",
                        help="how water molecules are choosed")
    parser.add_argument("-w", "--water", dest="water_model", default="tip3p",
                        choices=["tip3p", "tip5p"], action="store",
                        help="water model used (tip3p or tip5p)")
    parser.add_argument("-o", "--output", dest="output_prefix", default="water",
                        action="store", help="prefix add to output files")
    return parser.parse_args()


def main():
    args = cmd_lineparser()
    mol_file = args.mol_file
    fld_file = args.fld_file
    water_model = args.water_model
    n_layer = args.n_layer
    temperature = args.temperature
    how = args.how
    output_prefix = args.output_prefix

    """If the user does not provide any of these elements,
    we take those available per default in waterkit."""
    d = imp.find_module("waterkit")[1]
    ad_forcefield_file = os.path.join(d, "data/AD4_parameters.dat")
    ad_forcefield = AutoDockForceField(ad_forcefield_file, smooth=0, dielectric=1.)

    # Read PDBQT/MOL2 file, Waterfield file and AutoDock grid map
    molecule = Molecule.from_file(mol_file)
    ad_map = Map.from_fld(fld_file)

    # Go waterkit!!
    k = WaterKit()
    k.hydrate(molecule, ad_map, ad_forcefield, 
              water_model, how, temperature, n_layer)

    # Write output files
    k.write_shells(output_prefix, water_model)

if __name__ == "__main__":
    main()
