#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# prepare receptor
#

import argparse
import copy
import logging
import math
import os
import string
import sys

import parmed as pmd
from pdb4amber import AmberPDBFixer
from pdb4amber.utils import easy_call


# Added CYM residue
HEAVY_ATOM_DICT = {
    'ALA': 5,
    'ARG': 11,
    'ASN': 8,
    'ASP': 8,
    'CYS': 6,
    'GLN': 9,
    'GLU': 9,
    'GLY': 4,
    'HIS': 10,
    'ILE': 8,
    'LEU': 8,
    'LYS': 9,
    'MET': 8,
    'PHE': 11,
    'PRO': 7,
    'SER': 6,
    'THR': 7,
    'TRP': 14,
    'TYR': 12,
    'VAL': 7,
    'HID': 10,
    'HIE': 10,
    'HIN': 10,
    'HIP': 10,
    'CYX': 6,
    'CYM': 6,
    'ASH': 8,
    'GLH': 9,
    'LYH': 9
}

# Global constants
# Added CYM residue
RESPROT = ('ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS',
           'ILE', 'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP',
           'TYR', 'VAL', 'HID', 'HIE', 'HIN', 'HIP', 'CYX', 'CYM', 'ASH', 'GLH',
           'LYH', 'ACE', 'NME', 'GL4', 'AS4')

RESNA = ('C', 'G', 'U', 'A', 'DC', 'DG', 'DT', 'DA', 'OHE', 'C5', 'G5', 'U5',
         'A5', 'C3', 'G3', 'U3', 'A3', 'DC5', 'DG5', 'DT5', 'DA5', 'DC3',
         'DG3', 'DT3', 'DA3' )

RESSOLV = ('WAT', 'HOH', 'AG', 'AL', 'Ag', 'BA', 'BR', 'Be', 'CA', 'CD', 'CE',
           'CL', 'CO', 'CR', 'CS', 'CU', 'CU1', 'Ce', 'Cl-', 'Cr', 'Dy', 'EU',
           'EU3', 'Er', 'F', 'FE', 'FE2', 'GD3', 'HE+', 'HG', 'HZ+', 'Hf',
           'IN', 'IOD', 'K', 'K+', 'LA', 'LI', 'LU', 'MG', 'MN', 'NA', 'NH4',
           'NI', 'Na+', 'Nd', 'PB', 'PD', 'PR', 'PT', 'Pu', 'RB', 'Ra', 'SM',
           'SR', 'Sm', 'Sn', 'TB', 'TL', 'Th', 'Tl', 'Tm', 'U4+', 'V2+', 'Y',
           'YB2', 'ZN', 'Zr')

AMBER_SUPPORTED_RESNAMES = RESPROT + RESNA + RESSOLV


def _write_pdb_file(output_name, molecule,  overwrite=True, **kwargs):
    '''Write PDB file

    Args:
        output_name (str): pdbqt output filename
        molecule (parmed): parmed molecule object

    '''
    molecule.save(output_name, format='pdb', overwrite=overwrite, **kwargs)


def _write_pdbqt_file(output_name, molecule):
    '''Write PDBQT file

    Args:
        output_name (str): pdbqt output filename
        molecule (parmed): parmed molecule object

    '''
    pdbqt_str = '%-6s%5d %-4s %3s %s%4d    %8.3f%8.3f%8.3f  1.00  1.00    %6.3f %-2s\n'
    output_str = ''
    chain_id = 0

    for atom in molecule.atoms:
        if len(atom.name) < 4:
            name = ' %s' % atom.name
        else:
            name = atom.name

        resname = atom.residue.name
        resid = atom.residue.idx + 1

        # OpenBabel does not like atom types starting with a number
        if atom.type[0].isdigit():
            atom_type = atom.type[::-1]
        else:
            atom_type = atom.type

        # AutoGrid does not accept atom type name of length > 2
        atom_type = atom_type[:2]

        if resname in RESSOLV:
            atype = 'HETATM'
        else:
            atype = 'ATOM'

        output_str += pdbqt_str % (atype, atom.idx + 1, name, resname, string.ascii_uppercase[chain_id],
                                   resid, atom.xx, atom.xy, atom.xz, atom.charge, atom_type)

        if name.strip() == 'OXT':
            chain_id += 1

    if name.strip() != 'OXT':
        output_str += 'TER\n'
    output_str += 'END\n'

    with open(output_name, 'w') as w:
        w.write(output_str)


def _convert_amber_to_autodock_types(molecule):
    molecule = copy.deepcopy(molecule)

    amber_autodock_dict = {
        'N3': 'N',
        'H': 'HD',
        'CX': 'C',
        'HP': 'H',
        'CT': 'C',
        'HC': 'H',
        'C': 'C',
        'O': 'OA',
        'N': 'N',
        'H1': 'H',
        'C3': 'C',
        '3C': 'C',
        'C2': 'C',
        '2C': 'C',
        'CO': 'C',
        'O2': 'OA',
        'OH': 'OA',
        'HO': 'HD',
        'SH': 'SA',
        'HS': 'HD',
        'CA': 'A',
        'HA': 'H',
        'S': 'SA',
        'C8': 'C',
        'N2': 'N',
        'CC': 'A',
        'NB': 'NA',
        'CR': 'A',
        'CV': 'A',
        'H5': 'H',
        'NA': 'N',
        'CW': 'A',
        'H4': 'H',
        'C*': 'A',
        'CN': 'A',
        'CB': 'A',
        'Zn2+': 'Zn',
        'XC': 'C'
    }

    for atom in molecule.atoms:
        if atom.residue.name == 'TYR' and atom.name == 'CZ' and atom.type == 'C':
            atom.type = 'A'
        elif atom.residue.name == 'ARG' and atom.name == 'CZ' and atom.type == 'CA':
            atom.type = 'C'
        else:
            atom.type = amber_autodock_dict[atom.type]

    return molecule


def _make_leap_template(parm, ns_names, gaplist, sslist, input_pdb, prmtop='prmtop', rst7='rst7'):
    # Change ff14SB to ff19SB
    default_force_field = ('source leaprc.protein.ff14SB\n'
                           'source leaprc.DNA.OL15\n'
                           'source leaprc.RNA.OL3\n'
                           'source leaprc.water.tip3p\n'
                           'source leaprc.gaff2\n')

    leap_template = ('{force_fields}\n'
                     '{more_force_fields}\n'
                     'x = loadpdb {input_pdb}\n'
                     '{box_info}\n'
                     '{more_leap_cmds}\n'
                     'set default nocenter on\n'
                     'saveAmberParm x {prmtop} {rst7}\n'
                     'quit\n')

    # box
    box = parm.box
    if box is not None:
        box_info = 'set x box { %s  %s  %s }' % (box[0], box[1], box[2])
    else:
        box_info = ''

    # Now we can assume that we are dealing with AmberTools16:
    more_force_fields = ''

    for res in ns_names:
        more_force_fields += '%s = loadmol2 %s.mol2\n' % (res, res)
        more_force_fields += 'loadAmberParams %s.frcmod\n' % res

    #  more_leap_cmds
    more_leap_cmds = ''
    if gaplist:
        for d, res1, resid1, res2, resid2 in gaplist:
            more_leap_cmds += 'deleteBond x.%d.C x.%d.N\n' % (resid1 + 1, resid2 + 1)

    #  process sslist
    if sslist:
        for resid1, resid2 in sslist:
            more_leap_cmds += 'bond x.%d.SG x.%d.SG\n' % (resid1+1, resid2+1)

    leap_string = leap_template.format(
        force_fields=default_force_field,
        more_force_fields=more_force_fields,
        box_info=box_info,
        input_pdb=input_pdb,
        prmtop=prmtop,
        rst7=rst7,
        more_leap_cmds=more_leap_cmds)

    return leap_string


def _remove_alt_residues(molecule):
    # remove altlocs label
    residue_collection = []

    for residue in molecule.residues:
        for atom in residue.atoms:
            atom.altloc = ''
            for oatom in atom.other_locations.values():
                oatom.altloc = ''
                residue_collection.append(residue)

    residue_collection = list(set(residue_collection))

    return residue_collection


def _find_gaps(molecule, resprot):
    gaplist = []
    max_distance = 2.0

    for i, residue in enumerate(molecule.residues):
        if residue.ter:
            continue

        c_atom = [atom for atom in residue.atoms if atom.name == 'C'][0]
        n_atom = [atom for atom in molecule.residues[i + 1].atoms if atom.name == 'N'][0]

        dx = float(c_atom.xx) - float(n_atom.xx)
        dy = float(c_atom.xy) - float(n_atom.xy)
        dz = float(c_atom.xz) - float(n_atom.xz)
        gap = math.sqrt(dx * dx + dy * dy + dz * dz)

        if gap > max_distance:
            gaprecord = (gap, c_atom.residue.name, residue.number, 
                         n_atom.residue.name, molecule.residues[i + 1].number)
            gaplist.append(gaprecord)

    return gaplist


def _fix_isoleucine_cd_atom_name(molecule):
    ile_fixed = []

    for residue in molecule.residues:
        if residue.name == 'ILE':
            for atom in residue:
                if atom.name == 'CD':
                    atom.name = 'CD1'
                    ile_fixed.append(('ILE', residue.number))

    return ile_fixed


def _find_histidine(molecule):
    his_found = []

    for residue in molecule.residues:
        if residue.name == 'HIS':
            his_found.append(('HIS', residue.number))

    return his_found


def _fix_charmm_histidine_to_amber(molecule):
    his_fixed = []

    for residue in molecule.residues:
        if residue.name == 'HSE':
            residue.name = 'HIE'
            his_fixed.append(('HIE', residue.number))
        elif residue.name == 'HSD':
            residue.name = 'HID'
            his_fixed.append(('HID', residue.number))
        elif residue.name == 'HSP':
            residue.name = 'HIP'
            his_fixed.append(('HIP', residue.number))

    return his_fixed


def _find_non_standard_resnames(molecule, amber_supported_resname):
    ns_names = set()

    for residue in molecule.residues:
        if len(residue.name) > 3:
            rname = residue.name[:3]
        else:
            rname = residue.name
        if rname.strip() not in amber_supported_resname:
            ns_names.add(rname)

    return ns_names


class PrepareReceptor:

    def __init__(self, keep_hydrogen=False, keep_water=False, no_disulfide=False, keep_altloc=False, use_model=1):
        self._keep_hydrogen = keep_hydrogen
        self._keep_water = keep_water
        self._no_difsulfide = no_disulfide
        self._keep_altloc = keep_altloc
        self._use_model = use_model

        self._pdb_filename = None
        self._molecule = None

    def prepare(self, pdb_filename, prmtop_filename='protein.prmtop', rst7_filename='protein.rst7',
                pdb_clean_filename='protein_clean.pdb', clean=True):
        '''Prepare receptor structure
    
        Args:
            pdb_filename (str): input pdb filename
            prmtop_filename (str): Amber prmtop filename (default: protein.prmtop)
            rst7_filename (str): Amber coordinate filename (default: protein.rst7)
            pdb_clean_filename (str): temporary pdb filename (default: tmp_clean.pdb)
            clean (bool): remove tleap input and output files (default: True)

        '''
        final_ns_names = []
        tleap_input = 'leap.template.in'
        tleap_output = 'leap.template.out'
        tleap_log = 'leap.log'

        logger = logging.getLogger('WaterKit receptor preparation')
        logging.basicConfig(level=os.environ.get('LOGLEVEL', 'INFO'))

        try:
            receptor = pmd.load_file(pdb_filename)
        except FileNotFoundError:
            error_msg = 'Receptor file (%s) cannot be found.' % pdb_filename
            logger.error(error_msg)
            raise

        pdbfixer = AmberPDBFixer(receptor)

        # Remove box and symmetry
        pdbfixer.parm.box = None
        pdbfixer.parm.symmetry = None

        # Find all the gaps
        gaplist = _find_gaps(pdbfixer.parm, RESPROT)
        if gaplist:
            error_msg = 'Gap(s) found between the following residues.'
            error_msg += ' Please fix it/them by adding the missing residues'
            error_msg += ' or add TER records to indicate that the residues/chains are not physically connected'
            error_msg += ' to each other: \n'
            
            gap_msg = ' - gap of %lf A between %s %d and %s %d\n'
            for _, (d, resname0, resid0, resname1, resid1) in enumerate(gaplist):
                error_msg += gap_msg % (d, resname0, resid0 + 1, resname1, resid1 + 1)
            
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Find missing heavy atoms
        missing_atoms = pdbfixer.find_missing_heavy_atoms(HEAVY_ATOM_DICT)
        if missing_atoms:
            logger.warning('Found residue(s) with missing heavy atoms: %s' % ', '.join([str(m) for m in missing_atoms]))

        # Remove all the hydrogens
        if not self._keep_hydrogen:
            pdbfixer.parm.strip('@/H')
            logger.info('Removed all hydrogen atoms')

        # Remove water molecules
        if not self._keep_water:
            pdbfixer.remove_water()
            logger.info('Removed all water molecules')

        # Fix isoleucine CD aton name, supposed to be CD1 for Amber
        ile_fixed = _fix_isoleucine_cd_atom_name(pdbfixer.parm)
        if ile_fixed:
            logger.info('Atom names were fixed for: %s' % ', '.join('%s - %d' % (r[0], r[1]) for r in ile_fixed))

        his_fixed = _fix_charmm_histidine_to_amber(pdbfixer.parm)
        if his_fixed:
            warning_msg = 'CHARMM histidine protonation were converted to Amber: %s'
            logger.warning(warning_msg % ', '.join('%s - %d' % (r[0], r[1]) for r in his_fixed))

        # Keep only standard-Amber residues
        ns_names = _find_non_standard_resnames(pdbfixer.parm, AMBER_SUPPORTED_RESNAMES)
        if ns_names:
            pdbfixer.parm.strip('!:' + ','.join(AMBER_SUPPORTED_RESNAMES))
            logger.info('Removed all non-standard Amber residues: %s' % ', '.join(ns_names))

        his_found = _find_histidine(pdbfixer.parm)
        if his_found:
            warning_msg = 'Histidine protonation will be automatically assigned to HIE: %s'
            logger.warning(warning_msg % ', '.join('%s - %d' % (r[0], r[1]) for r in his_found))

        # Assign histidine protonations
        pdbfixer.assign_histidine()

        # Find all the disulfide bonds
        if not self._no_difsulfide:
            sslist, cys_cys_atomidx_set = pdbfixer.find_disulfide()
            if sslist:
                pdbfixer.rename_cys_to_cyx(sslist)
                resids_str = ', '.join(['%s-%s' % (ss[0], ss[1]) for ss in sslist])
                logger.info('Found disulfide bridges between residues %s' % resids_str)
        else:
            sslist = None

        # Remove all the aternate residue sidechains
        if not self._keep_altloc:
            alt_residues = _remove_alt_residues(pdbfixer.parm)
            if alt_residues:
                logger.info('Removed all alternatives residue sidechains')

        # Write cleaned PDB file
        final_coordinates = pdbfixer.parm.get_coordinates()[self._use_model - 1]
        write_kwargs = dict(coordinates=final_coordinates)
        write_kwargs['increase_tercount'] = False # so CONECT record can work properly
        write_kwargs['altlocs'] = 'occupancy'

        try:
            _write_pdb_file(pdb_clean_filename, pdbfixer.parm, **write_kwargs)
        except:
            error_msg = 'Could not write pdb file %s'  % pdb_clean_filename
            logger.error(error_msg)
            raise

        # Generate topology/coordinates files
        with open('leap.template.in', 'w') as w:
            content = _make_leap_template(pdbfixer.parm, final_ns_names, gaplist, sslist,
                                          input_pdb=pdb_clean_filename,
                                          prmtop=prmtop_filename, rst7=rst7_filename)
            w.write(content)

        try:
            easy_call('tleap -s -f %s > %s' % (tleap_input, tleap_output), shell=True)
        except RuntimeError:
            error_msg = 'Could not generate topology/coordinates files with tleap'
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        self._molecule = pmd.load_file(prmtop_filename, rst7_filename)

        if clean:
            os.remove(tleap_input)
            os.remove(tleap_output)
            os.remove(tleap_log)

    def write_pdb_file(self, pdb_filename='protein.pdb'):
        _write_pdb_file(pdb_filename, self._molecule)

    def write_pdbqt_file(self, pdbqt_filename='protein.pdbqt', amber_atom_types=False):
        if amber_atom_types:
            _write_pdbqt_file(pdbqt_filename, self._molecule)
        else:
            molecule = _convert_amber_to_autodock_types(self._molecule)
            _write_pdbqt_file(pdbqt_filename, molecule)


def cmd_lineparser():
    parser = argparse.ArgumentParser(description='prepare receptor')
    parser.add_argument('-i', '--in', required=True,
        dest='pdb_filename', help='PDB input file (default: stdin)',
        default='stdin')
    parser.add_argument('-o', '--out', default='protein',
        dest='output_prefix', help='output prefix filename (default: protein)')
    parser.add_argument('--keep_hydrogen', action='store_true', default=False,
        dest='keep_hydrogen', help='keep all hydrogen atoms (default: no)')
    parser.add_argument('--no_disulfide', action='store_true', default=False,
        dest='no_disulfide', help='ignore difsulfide bridges (default: no)')
    parser.add_argument('--keep_water', action='store_true', default=False,
        dest='keep_water', help='keep all water molecules (default: no)')
    parser.add_argument('--keep_altloc', action='store_true', default=False,
        dest='keep_altloc', help='keep residue altloc (default is to keep "A")')
    parser.add_argument('--model', type=int, default=1,
        dest='use_model',
        help='Model to use from a multi-model pdb file (integer).  (default: use 1st model). '
        'Use a negative number to keep all models')
    parser.add_argument('--pdb', dest='make_pdb', default=False,
        action='store_true', help='generate pdb file')
    parser.add_argument('--pdbqt', dest='make_pdbqt', default=False,
        action='store_true', help='PDBQT file with AutoDock atom types')
    parser.add_argument('--amber_pdbqt', dest='make_amber_pdbqt', default=False,
        action='store_true', help='DBQT file with Amber atom types')
    return parser.parse_args()


def main():
    args = cmd_lineparser()
    pdb_filename = args.pdb_filename
    output_prefix = args.output_prefix
    keep_hydrogen = args.keep_hydrogen
    no_disulfide = args.no_disulfide
    keep_water = args.keep_water
    keep_altloc = args.keep_altloc
    use_model = args.use_model
    make_pdb = args.make_pdb
    make_pdbqt = args.make_pdbqt
    make_amber_pdbqt = args.make_amber_pdbqt

    prmtop_filename = '%s.prmtop' % output_prefix
    rst7_filename = '%s.rst7' % output_prefix
    pdb_clean_filename = '%s_clean.pdb' % output_prefix

    pr = PrepareReceptor(keep_hydrogen, keep_water, no_disulfide, keep_altloc, use_model)
    pr.prepare(pdb_filename, prmtop_filename, rst7_filename, pdb_clean_filename)

    if make_pdb:
        pdb_prepared_filename = '%s.pdb' % output_prefix
        pr.write_pdb_file(pdb_prepared_filename)

    if make_pdbqt:
        pdbqt_prepared_filename = '%s.pdbqt' % output_prefix
        pr.write_pdbqt_file(pdbqt_prepared_filename)

    if make_amber_pdbqt:
        pdbqt_prepared_filename = '%s_amber.pdbqt' % output_prefix
        pr.write_pdbqt_file(pdbqt_prepared_filename, amber_atom_types=True)


if __name__ == '__main__':
    main()