#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# WaterKit
#
# Class for water network optimizer
#

import warnings

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster

import utils


class WaterOptimizer():

    def __init__(self, water_box, how='best', distance=3.4, angle=145, rotation=10,
                 energy_cutoff=0, temperature=298.15):
        self._water_box = water_box
        self._how = how
        self._distance = distance
        self._angle = angle
        self._rotation = rotation
        self._temperature = temperature
        self._energy_cutoff = energy_cutoff
        # Boltzmann constant (kcal/mol)
        self._kb = 0.0019872041
        # Optimal distance between O and H
        self._opt_distance = 1.9

    def _cluster(self, waters, distance=2., method='single'):
        """ Cluster water molecule based on their position using hierarchical clustering """
        coordinates = np.array([w.coordinates([0])[0] for w in waters])

        # Clustering
        Z = linkage(coordinates, method=method, metric='euclidean')
        clusters = fcluster(Z, distance, criterion='distance')
        return clusters

    def _boltzmann_choice(self, energies):
        """Choose state i based on boltzmann probability."""
        energies = np.array(energies)
        d = np.exp(-energies / (self._kb * self._temperature))
        # We ignore divide by zero warning
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            p = d / np.sum(d)
        i = np.random.choice(d.shape[0], p=p)
        return i

    def _smooth_distance(self, r, rij):
        smooth = 0.5

        if rij - 0.5 * smooth < r < rij + .5 * smooth :
            return rij
        elif r >= rij + .5 * smooth:
            return r - .5 * smooth
        elif r <= rij - 0.5 * smooth:
            return r + .5 * smooth

    def _hydrogen_bond_distance(self, r, a, c):
        rs = self._smooth_distance(r, self._opt_distance)
        return ((a/(rs**12)) - (c/(rs**10)))

    def _hydrogen_bond_angle(self, angles):
        score = 1.
        angle_90 = np.pi / 2.

        for angle in angles:
            if angle < angle_90:
                score *= np.cos(angle)**2
            else:
                score *= 0.

        return score

    def _energy_pairwise(self, water_xyz, anchors_xyz, vectors_xyz, anchors_types):
        energy = 0.

        for i, xyz in enumerate(water_xyz[1:]):
            if i <= 1:
                ref_xyz = xyz # use hydrogen for distance
                water_type = 'donor'
            else:
                ref_xyz = water_xyz[0] # use oxygen for distance
                water_type = 'acceptor'

            for anchor_xyz, vector_xyz, anchor_type in zip(anchors_xyz, vectors_xyz, anchors_types):
                """ water and anchor types have to be opposite types
                in order to have an hydrogen bond between them """
                if water_type != anchor_type:
                    beta_1 = utils.get_angle(xyz, anchor_xyz, vector_xyz, False)[0]
                    beta_2 = utils.get_angle(xyz + utils.vector(water_xyz[0], xyz), xyz, anchor_xyz, False)[0]
                    score_a = self._hydrogen_bond_angle([beta_1, beta_2])
                    r = utils.get_euclidean_distance(ref_xyz, np.array([anchor_xyz]))[0]
                    score_d = self._hydrogen_bond_distance(r, 55332.873, 18393.199)
                    energy += score_a * score_d

        return energy

    def _optimize_disordered_waters(self, receptor, waters, connections, ad_map):
        """Optimize water molecules on rotatable bonds."""
        disordered_energies = []
        rotatable_bonds = receptor.rotatable_bonds

        # Number of rotation necessary to do a full spin
        n_rotation = np.int(np.floor((360 / self._rotation))) - 1
        rotation = np.radians(self._rotation)

        # Iterate through every disordered bonds
        for match, value in rotatable_bonds.iteritems():
            energies = []
            angles = []
            rot_waters = []

            # Get index of all the waters attached
            # to a disordered group by looking at the connections
            for atom_id in match:
                if atom_id in connections['atom_i'].values:
                    index = connections.loc[connections['atom_i'] == atom_id]['molecule_j'].values
                    rot_waters.extend([waters[i] for i in index])

            # Get energy of the favorable disordered waters
            energy_waters = np.array([ad_map.energy(w.atom_informations()) for w in rot_waters])
            energy_waters[energy_waters > 0] = 0
            energies.append(np.sum(energy_waters))
            # Current angle of the disordered group
            current_angle = np.radians(receptor._OBMol.GetTorsion(match[3]+1, match[2]+1, match[1]+1, match[0]+1))
            angles.append(current_angle)

            """ Find all the atoms that depends on these atoms. This
            will be useful when we will want to rotate a whole sidechain."""
            # Atom children has to be initialized before
            # molecule._OBMol.FindChildren(atom_children, match[2], match[3])
            # print np.array(atom_children)

            # Atoms 1 and 2 define the rotation axis
            p1 = receptor.coordinates(match[2])[0]
            p2 = receptor.coordinates(match[1])[0]

            # Scan all the angles
            for i in range(n_rotation):
                """TODO: Performance wise, we shouldn't update water
                coordinates everytime. Coordinates should be extracted
                before doing the optimization and only at the end
                we update the coordinates of the water molecules."""
                for rot_water in rot_waters:
                    p0 = rot_water.coordinates([0])[0]
                    p_new = utils.rotate_point(p0, p1, p2, rotation)
                    rot_water.update_coordinates(p_new, atom_id=0)

                # Get energy and update the current angle (increment rotation)
                energy_waters = np.array([ad_map.energy(w.atom_informations()) for w in rot_waters])
                energy_waters[energy_waters > 0] = 0
                energies.append(np.sum(energy_waters))
                current_angle += rotation
                angles.append(current_angle)

            # Choose the best or the best-boltzmann state
            if self._how == 'best':
                i = np.argmin(energies)
            elif self._how == 'boltzmann':
                i = self._boltzmann_choice(energies)

            disordered_energies.append(energies[i])

            # Calculate the best angle, based on how much we rotated
            best_angle = np.radians((360. - np.degrees(current_angle)) + np.degrees(angles[i]))
            # Update coordinates to the choosen state
            for rot_water in rot_waters:
                p0 = rot_water.coordinates([0])[0]
                p_new = utils.rotate_point(p0, p1, p2, best_angle)
                rot_water.update_coordinates(p_new, atom_id=0)
                # Update also the anchor point
                anchor = rot_water._anchor
                anchor[0] = utils.rotate_point(anchor[0], p1, p2, best_angle)
                anchor[1] = utils.rotate_point(anchor[1], p1, p2, best_angle)

        return disordered_energies

    def _optimize_position(self, water, ad_map):
        """Optimize the position of the spherical water molecule. 

        The movement of the water is contrained by the distance and 
        the angle with the anchor.
        """
        oxygen_type = water.atom_types([0])[0]
        max_radius = self._distance
        min_radius = 2.5

        """If the anchor type is donor, we have to reduce the
        radius by 1 angstrom. Because the hydrogen atom is closer
        to the water molecule than the heavy atom."""
        if water._anchor_type == 'donor':
            min_radius -= 1.
            max_radius -= 1.

        """This is how we select the allowed positions:
        1. Get all the point on the grid around the anchor (sphere)
        2. Compute angles between all the coordinates and the anchor
        3. Select coordinates with an angle superior to the choosen angle
        4. Get their energy"""
        coord_sphere = ad_map.neighbor_points(water._anchor[0], min_radius, max_radius)
        angle_sphere = utils.get_angle(coord_sphere, water._anchor[0], water._anchor[1])
        coord_sphere = coord_sphere[angle_sphere >= self._angle]
        energy_sphere = ad_map.energy_coordinates(coord_sphere, atom_type=oxygen_type)

        # Energy of the spherical water
        energy_water = ad_map.energy(water.atom_informations())

        if energy_sphere.size:
            if self._how == 'best':
                i = energy_sphere.argmin()
            elif self._how == 'boltzmann':
                i = self._boltzmann_choice(energy_sphere)

            # Update the coordinates
            water.translate(utils.vector(water.coordinates(0), coord_sphere[i]))

            return energy_sphere[i]

        return energy_water

    def _optimize_orientation(self, water):
        """Optimize the orientation of the water molecule."""
        anchors_xyz = []
        vectors_xyz = []
        anchors_ids = []
        anchors_types = []
        energies = []
        angles = []

        if water._anchor_type == 'donor':
            ref_id = 3
        else:
            ref_id = 1

        water_xyz = water.coordinates()
        # Number of rotation necessary to do a full spin
        n_rotation = np.int(np.floor((360 / self._rotation))) - 1
        # Get all the neighborhood atoms (active molecules)
        closest_atom_ids = self._water_box.closest_atoms(water_xyz[0], 3.4)

        # Retrieve the coordinates of all the anchors
        for _, row in closest_atom_ids.iterrows():
            molecule = self._water_box.molecules[row['molecule_i']]

            # Get anchors ids
            anchor_ids = molecule.hydrogen_bond_anchors.keys()
            closest_anchor_ids = list(set([row['atom_i']]).intersection(anchor_ids))

            # Get rotatable bonds ids
            try:
                rotatable_bond_ids = molecule.rotatable_bonds.keys()
            except:
                rotatable_bond_ids = []

            for idx in closest_anchor_ids:
                anchor_xyz = molecule.coordinates(idx)
                anchor_type = molecule.hydrogen_bond_anchors[idx].type

                if [idx for i in rotatable_bond_ids if idx in i]:
                    """ If the vectors are on a rotatable bond 
                    we change them in order to be always pointing to
                    the water molecule (perfect HB). In fact the vector
                    is now the coordinate of the oxygen atom. And we
                    keep only one vector, we don't want to count it twice"""
                    v = water_xyz[0]
                    a = anchor_xyz
                else:
                    # Otherwise, get all the vectors on this anchor
                    v = molecule.hydrogen_bond_anchors[idx].vectors
                    a = np.tile(anchor_xyz, (v.shape[0], 1))

                anchors_xyz.append(a)
                vectors_xyz.append(v)
                anchors_ids.extend([idx] * v.shape[0])
                anchors_types.extend([anchor_type] * v.shape[0])

        anchors_xyz = np.vstack(anchors_xyz)
        vectors_xyz = np.vstack(vectors_xyz)

        # Get the energy of the current orientation
        energy_water = self._energy_pairwise(water_xyz, anchors_xyz, vectors_xyz, anchors_types)
        energies.append(energy_water)
        # Set the current to 0, there is no angle reference
        current_angle = 0.
        angles.append(current_angle)

        # Rotate the water molecule and get its energy
        for i in range(n_rotation):
            water.rotate(self._rotation, ref_id=ref_id)
            water_xyz = water.coordinates()

            # Get energy and update the current angle (increment rotation)
            energies.append(self._energy_pairwise(water_xyz, anchors_xyz, vectors_xyz, anchors_types))
            current_angle += self._rotation
            angles.append(current_angle)

        if self._how == 'best':
            i = np.argmin(energies)
        elif self._how == ' boltzmann':
            i = self._boltzmann_choice(energies)

        # Once we checked all the angles, we rotate the water molecule to the best angle
        # But also we have to consider how much we rotated the water molecule before
        best_angle = (360. - current_angle) + angles[i]
        water.rotate(best_angle, ref_id=ref_id)

        return energies[i]

    def optimize(self, waters, connections=None, opt_position=True, opt_rotation=True, opt_disordered=True):
        """Optimize position of water molecules."""
        df = {}
        data = []
        profiles = []
        to_be_removed = []

        shell_id = self._water_box.number_of_shells(ignore_xray=True)
        ad_map = self._water_box.map

        if opt_disordered and connections is not None:
            receptor = self._water_box.molecules_in_shell(0)[0]
            # Start first by optimizing the disordered water molecules
            self._optimize_disordered_waters(receptor, waters, connections, ad_map)

        """And now we optimize all water individually. All the
        water molecules are outside the box or with a positive
        energy are considered as bad and are removed."""
        for i, water in enumerate(waters):
            if ad_map.is_in_map(water.coordinates(0)[0]):
                # Optimize the position of the spherical water
                if opt_position:
                    energy_position = self._optimize_position(water, ad_map)
                else:
                    energy_position = ad_map.energy(water.atom_informations())

                # Before going further we check the energy
                if energy_position <= self._energy_cutoff:
                    # Build the TIP5
                    # TODO: Should be outside this function
                    water.build_tip5p()

                    # Optimize the rotation
                    if opt_rotation:
                        energy_orientation = self._optimize_orientation(water)
                    else:
                        energy_orientation = None

                    # TODO: Doublon, all the information should be stored in waterbox df
                    water.energy = energy_position
                    data.append((shell_id + 1, energy_position, energy_orientation))
                else:
                    to_be_removed.append(i)
            else:
                to_be_removed.append(i)

        # Keep only the good waters
        waters = [water for i, water in enumerate(waters) if not i in to_be_removed]
        # Keep connections of the good waters
        if connections is not None:
            index = connections.loc[connections['molecule_j'].isin(to_be_removed)].index
            connections.drop(index, inplace=True)
            # Renumber the water molecules
            connections['molecule_j'] = range(0, len(waters))
            df['connections'] = connections

        # Add water shell informations
        columns = ['shell_id', 'energy_position', 'energy_orientation']
        df_shell = pd.DataFrame(data, columns=columns)
        df['shells'] = df_shell

        return (waters, df)

    def activate_molecules_in_shell(self, shell_id):
        """Activate waters in the shell."""
        clusters = []
        cluster_distance = 2.7
        minimal_distance = 2.5

        waters = self._water_box.molecules_in_shell(shell_id, active_only=False)
        df = self._water_box.molecule_informations_in_shell(shell_id)

        # The dataframe and the waters list must have the same index
        df.reset_index(drop=True, inplace=True)

        if self._how == 'best' or self._how == 'boltzmann':
            if len(waters) > 1:
                # Identify clusters of waters
                clusters = self._cluster(waters, distance=cluster_distance)
            elif len(waters) == 1:
                clusters = [1]

            df['cluster_id'] = clusters

            for i, cluster in df.groupby('cluster_id', sort=False):
                to_activate = []

                cluster = cluster.copy()

                """This is how we cluster water molecules:
                1. We identify the best or the bolzmann-best water molecule in the 
                cluster, by taking first X-ray water molecules, if not the best 
                water molecule in term of energy. 
                2. Calculate the distance with the best(s) and all the
                other water molecules. The water molecules too close are removed 
                and are kept only the ones further than 2.4 A. 
                3. We removed the best and the water that are clashing from the dataframe.
                4. We continue until there is nothing left in the dataframe."""
                while cluster.shape[0] > 0:
                    to_drop = []

                    if True in cluster['xray'].values:
                        best_water_ids = cluster[cluster['xray'] == True].index.values
                    else:
                        if self._how == 'best':
                            best_water_ids = [cluster['energy_position'].idxmin()]
                        elif self._how == 'boltzmann':
                            i = self._boltzmann_choice(cluster['energy_position'].values)
                            best_water_ids = [cluster.index.values[i]]

                    water_ids = cluster.index.difference(best_water_ids).values

                    if water_ids.size > 0:
                        waters_xyz = np.array([waters[x].coordinates(0)[0] for x in water_ids])

                        for best_water_id in best_water_ids:
                            best_water_xyz = waters[best_water_id].coordinates(0)
                            d = utils.get_euclidean_distance(best_water_xyz, waters_xyz)
                            to_drop.extend(water_ids[np.argwhere(d < minimal_distance)].flatten())

                    to_activate.extend(best_water_ids)
                    cluster.drop(best_water_ids, inplace=True)
                    cluster.drop(to_drop, inplace=True)

                # The best water identified are activated
                df.loc[to_activate, 'active'] = True

        elif how == 'all':
            df['active'] = True

        # We update the information to able to build the next hydration shell
        self._water_box.update_informations_in_shell(df['active'].values, shell_id, 'active')
