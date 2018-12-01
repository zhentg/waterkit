#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# WaterKit
#
# AutoDock ForceField
#

import argparse
import imp
import os
import multiprocessing
import re
import time
import warnings

import pandas as pd
import numpy as np

import utils


warnings.filterwarnings("ignore")


class AutoDockForceField():
    def __init__(self, parameter_file=None, hb_cutoff=8, elec_cutoff=20, weighted=True):
        if parameter_file is None:
            d = imp.find_module('waterkit')[1]
            parameter_file = os.path.join(d, 'data/AD4_parameters.dat')

        self.weights = self._set_weights(parameter_file, weighted)
        self.atom_par = self._set_atom_parameters(parameter_file)
        self.pairwise = self._build_pairwise_table()

        # Parameters
        self.hb_cutoff = hb_cutoff
        self.elec_cutoff = elec_cutoff

        # VdW and hydrogen bond
        self.smooth = 0.5

        # Desolvation constants
        self.desolvation_k = 0.01097

        # Dielectric constants
        self.dielectric_epsilon = 78.4
        self.dielectric_A = -8.5525
        self.dielectric_B = self.dielectric_epsilon - self.dielectric_A
        self.dielectric_lambda = 0.003627
        self.dielectric_k = 7.7839
        self.elec_scale = 332.06363

    def _set_weights(self, parameter_file, weighted=True):
        """Get weights from parameter file."""
        weights = {}

        with open(parameter_file) as f:
            for line in f.readlines():
                if re.search('^FE_coeff', line):
                    line = line.split()
                    weight_name = line[0].split('_')[2]

                    if weighted:
                        weight_value = np.float(line[-1])
                    else:
                        weight_value = 1.

                    weights[weight_name] = weight_value

        return weights

    def _set_atom_parameters(self, parameter_file):
        columns = ['type', 'rii', 'epsii', 'vol', 'solpar', 'rij_hb',
                   'epsij_hb', 'hbond', 'rec_index', 'map_index',
                   'bond_index']
        data = []

        with open(parameter_file) as f:
            for line in f.readlines():
                if re.search('^atom_par', line):
                    line = line.split()
                    data.append((line[1], np.float(line[2]), np.float(line[3]), 
                                 np.float(line[4]), np.float(line[5]), np.float(line[6]), 
                                 np.float(line[7]), np.int(line[8]), np.int(line[9]), 
                                 np.int(line[10]), np.int(line[11])))
        
        atom_par = pd.DataFrame(data=data, columns=columns)
        atom_par.set_index('type', inplace=True)
        return atom_par

    def load_intnbp_r_eps_from_dpf(self, dp_file):
        """Load intnbp_r_eps from dpf file."""
        pass

    def deactivate_pairs(self, pairs):
        """Deactivate pairwise interactions between atoms."""
        if all(isinstance(pair, list) and len(pair) == 2 for pair in pairs):
            for pair in pairs:
                try:
                    self.pairwise.loc[(pair[0], pair[1]), 'active'] = False
                    self.pairwise.loc[(pair[1], pair[0]), 'active'] = False
                except:
                    print "Error: pair %s - %s does not exist." % (pair[0], pair[1])
        else:
            print "Error: pairs argument must be a list of list(2)."

    def _coefficient(self, epsilon, reqm, a, b):
        """Compute coefficients."""
        return (a / np.abs(a - b)) * epsilon * reqm**b

    def _build_pairwise_table(self):
        """Pre-compute all pairwise interactions."""
        columns = ['i', 'j', 'vdw_rij', 'vdw_epsij', 'A', 
                   'B', 'hb_rij', 'hb_epsij', 'C', 'D', 'active']
        data = []

        for i in self.atom_par.index:
            for j in self.atom_par.index:
                # vdW
                vdw_rij = (self.atom_par.loc[i]['rii'] + self.atom_par.loc[j]['rii']) / 2.
                vdw_epsij = np.sqrt(self.atom_par.loc[i]['epsii'] * self.atom_par.loc[j]['epsii'])
                a = self._coefficient(vdw_epsij, vdw_rij, 6, 12)
                b = self._coefficient(vdw_epsij, vdw_rij, 12, 6)

                # Hydrogen bond
                hbond_i = self.atom_par.loc[i]['hbond']
                hbond_j = self.atom_par.loc[j]['hbond']

                if hbond_i in [1, 2] and hbond_j in [3, 4, 5]:
                    hb_rij = self.atom_par.loc[j]['rij_hb']
                    hb_epsij = self.atom_par.loc[j]['epsij_hb']
                elif hbond_i in [3, 4, 5] and hbond_j in [1, 2]:
                    hb_rij = self.atom_par.loc[i]['rij_hb']
                    hb_epsij = self.atom_par.loc[i]['epsij_hb']
                else:
                    hb_rij = 0
                    hb_epsij = 0

                c = self._coefficient(hb_epsij, hb_rij, 10, 12)
                d = self._coefficient(hb_epsij, hb_rij, 12, 10)

                data.append((i, j, vdw_rij, vdw_epsij, a, b, hb_rij, hb_epsij, c, d, True))

        pairwise = pd.DataFrame(data=data, columns=columns)
        pairwise.set_index(['i', 'j'], inplace=True)
        return pairwise

    def smooth_distance(self, r, reqm, smooth=0.5):
        """Smooth distance."""
        # Otherwise we changed r in-place.
        r = r.copy()
        sf = .5 * smooth
        r[((reqm - sf) < r) & (r < (reqm + sf))] = reqm
        r[r >= reqm + sf] -= sf
        r[r <= reqm - sf] += sf
        return r

    def van_der_waals(self, r, reqm, A, B):
        """Compute VdW interaction."""
        r = self.smooth_distance(r, reqm, self.smooth)
        return np.sum((A / r**12) - (B / r**6))

    def hydrogen_bond_distance(self, r, reqm, C, D):
        """Compute hydrogen bond distance-based interaction."""
        if r <= self.hb_cutoff:
            r = self.smooth_distance(r, reqm, self.smooth)
            return np.sum((C / r**12) - (D / r**10))
        else:
            return 0.

    def hydrogen_bond_angle(self, atom_i_xyz, atom_j_xyz, vector_i_xyz, vector_j_xyz):
        """Compute hydrogen bond angle-based interaction."""
        beta_1 = utils.get_angle(atom_i_xyz, atom_j_xyz, vector_j_xyz, False)[0]
        beta_2 = utils.get_angle(atom_j_xyz, atom_i_xyz, vector_i_xyz, False)[0]

        angles = np.array([beta_1, beta_2])
        scores = np.cos(angles)
        scores[angles >= np.pi / 2.] = 0.
        score = np.prod(scores)

        return score

    def distance_dependent_dielectric(self, r):
        """Distance dependent dielectric, mehler and solmajer."""
        lambda_B = -self.dielectric_lambda * self.dielectric_B
        return self.dielectric_A + self.dielectric_B / (1. + self.dielectric_k * np.exp(lambda_B * r))

    def electrostatic(self, r, qi, qj):
        """Compute electrostatic interaction."""
        if r <= self.elec_cutoff:
            r_ddd = self.distance_dependent_dielectric(r)
            return np.sum(self.elec_scale * qi * qj / (r * r_ddd))
        else:
            return 0.

    def desolvation(self, r, qi, qj, ai, aj, vi, vj, sigma=3.6):
        """Compute desolvatation interaction."""
        desolv = (ai * vj) + (aj * vi)
        desolv += (self.desolvation_k * np.abs(qi) * vj) + (self.desolvation_k * np.abs(qj) * vi)
        desolv *= np.exp(-0.5 * (r**2 / sigma**2))
        return np.sum(desolv)

    def intermolecular_energy(self, atoms_i, atoms_j, hbs_i=None, hbs_j=None, details=False):
        """Compute total interaction energy."""
        desolv = 0.
        elec = 0.
        hb = 0.
        total = 0.
        vdw = 0.

        for _, atom_i in atoms_i.iterrows():
            # Get HB vectors from atom i
            if hbs_i is not None and hbs_j is not None:
                hb_i = hbs_i.loc[hbs_i['atom_i'] == atom_i['atom_i']]

            for _, atom_j in atoms_j.iterrows():
                pairwise = self.pairwise.loc[(atom_i['atom_type'], atom_j['atom_type'])]

                if pairwise['active']:
                    r = utils.get_euclidean_distance(np.array(atom_i['atom_xyz']), np.array([atom_j['atom_xyz']]))

                    """ We do not want to calculate useless thing
                    if the weight is equal to zero."""
                    if self.weights['hbond'] > 0 and pairwise['hb_rij'] > 0:
                        hb_distance = self.hydrogen_bond_distance(r, pairwise['hb_rij'], pairwise['C'], pairwise['D'])

                        # Get HB vectors from atom j
                        # Calculate directional HB if HB vectors provided
                        if hbs_i is not None and hbs_j is not None:
                            hb_j = hbs_j.loc[hbs_j['atom_i'] == atom_j['atom_i']]

                            hb_angles = []

                            for h_i in hb_i.iterrows():
                                for h_j in hb_j.iterrows():
                                    hb_angle = self.hydrogen_bond_angle(atom_i['atom_xyz'], atom_j['atom_xyz'], 
                                                                        h_i['vector_xyz'], h_j['vector_xyz'])
                                    hb_angles.append(hb_angle)

                            hb += np.sum(hb_distance * np.array(hb_angles))
                        else:
                            hb += hb_distance

                    if self.weights['vdW'] > 0:
                        vdw += self.van_der_waals(r, pairwise['vdw_rij'], pairwise['A'], pairwise['B'])

                    if self.weights['estat'] > 0:
                        elec += self.electrostatic(r, atom_i['atom_q'], atom_j['atom_q'])

                    if self.weights['desolv'] > 0:
                        desolv += self.desolvation(r, atom_i['atom_q'], atom_j['atom_q'],
                                                   self.atom_par.loc[atom_i['atom_type']]['solpar'],
                                                   self.atom_par.loc[atom_j['atom_type']]['solpar'],
                                                   self.atom_par.loc[atom_i['atom_type']]['vol'],
                                                   self.atom_par.loc[atom_j['atom_type']]['vol'])

        hb *= self.weights['hbond']
        elec *= self.weights['estat']
        vdw *= self.weights['vdW']
        desolv *= self.weights['desolv']
        total = hb + vdw + elec + desolv

        if details:
            return np.array([total, hb, vdw, elec, desolv])
        else:
            return total
