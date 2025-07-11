#!/usr/bin/env python
"""Extend a existed aiida-pseudo pseudo family."""

import json
import os
from pathlib import Path
import re
import sys

from fit_hydrogenics import fit_ortho_projectors, fit_rsq_projector, r_hydrogenic
from projectors import newProjector, newProjectors
from upfdict import newUPFDict

from aiida import load_profile, orm

root_dir = Path(__file__).absolute().parent.resolve()

### -> Set OpenMX location <- ###
pao_path = root_dir / "openmx3.9/DFT_DATA19/PAO/"
if not pao_path.exists():
    print(
        "Please download the OpenMX package at "
        "https://www.openmx-square.org/openmx3.9.tar.gz"
        " and extract it to the same directory as this script."
    )
    sys.exit(1)


def main():
    """Extend a existed aiida-pseudo pseudo family."""

    load_profile()
    projectors = {}
    # Generate a list of required atomic orbitals
    with open(root_dir / "required_orbitals.json", encoding="utf-8") as fp:
        required_orbital_list = json.load(fp)
    ###-> Choose the pseudo family (aiida-pseudo family) <-###
    pseudo_group = "PseudoDojo/0.4/PBE/FR/standard/upf"
    upfs = orm.load_group(pseudo_group)
    pseudo_group_dir = pseudo_group.replace("/", "_")
    with open(
        root_dir / "../../src/aiida_wannier90_workflows/utils/pseudo/data/semicore" /
        ###-> Choose the semicore list of the selected package <-###
        # "PseudoDojo_0.4_PBE_FR_standard_upf.json",
        (pseudo_group_dir + ".json"),
        encoding="utf-8",
    ) as fin:
        pswfc = json.load(fin)

    for element in pswfc:
        pswfc[element]["additional"] = []
        if element in required_orbital_list:
            for ao in required_orbital_list[element]:
                if ao.upper() not in pswfc[element]["pswfcs"]:
                    pswfc[element]["additional"].append(ao)
    # If you want to add orbitals to specific element:
    # pswfc["Ba"].update({"additional": ["5d", "6p"]})

    str2l = {"s": 0, "p": 1, "d": 2, "f": 3}
    for upf in upfs.nodes:  # pylint: disable=too-many-nested-blocks
        element = upf.element
        if element not in required_orbital_list:
            continue
        print(element)

        proj_ele = []
        if element not in pswfc.keys():
            continue
        upfdict = newUPFDict.from_str(upf.get_content())
        proj = upfdict.to_projectors()
        try:
            proj[0].j
        except AttributeError:
            spin_orbit = False
        else:
            spin_orbit = True
        # Add additional projectors
        # Create a directory to store projectors
        os.makedirs(root_dir / "external_projector" / pseudo_group_dir, exist_ok=True)
        for addit_orb in pswfc[element]["additional"]:
            print(addit_orb)
            l = str2l[addit_orb[1]]
            n = len([_ for _ in pswfc[element]["pswfcs"] if addit_orb[1].upper() in _])
            if n == 0:
                # no inner shell found, can only find orbitals from third-party PAO library
                pao_file = (
                    pao_path
                    / [
                        _
                        for _ in os.listdir(pao_path)
                        if re.match(rf"{element}[0-9]*\.0.*\.pao", _)
                    ][0]
                )
                pao = newProjectors.from_pao(pao_file, n, l)[0]
                alpha = fit_rsq_projector(pao, n)
                print(pao_file, ":", element, n, l, alpha)
                x = proj[0].x
                r = proj[0].r
                y = r_hydrogenic(r, l, n, alpha)
                if spin_orbit:
                    proj.add_projector_soc(
                        newProjector(x, y, l, label=addit_orb, alpha=alpha)
                    )
                else:
                    proj.add_projector(
                        newProjector(x, y, l, label=addit_orb, alpha=alpha)
                    )
            else:
                if not spin_orbit:
                    ref = None
                    for p in proj:
                        if (int(p.label[0]) == int(addit_orb[0]) - 1) and (
                            p.label[1].lower() == addit_orb[1].lower()
                        ):
                            ref = p
                else:  # spin_orbit
                    ref = []
                    for p in proj:
                        if (int(p.label[0]) == int(addit_orb[0]) - 1) and (
                            p.label[1].lower() == addit_orb[1].lower()
                        ):
                            ref.append(p)

                if ref is None:
                    raise ValueError(f"Cant find inner projectors for {addit_orb}")
                if isinstance(ref, list):
                    if not len(ref) in [1, 2]:
                        raise ValueError(
                            f"Wrong inner projectors for {addit_orb}, found {len(ref)}"
                        )
                print("fit from pao ortho")
                if spin_orbit:
                    for ref_ in ref:
                        alpha = fit_ortho_projectors(ref_, n)
                        x = proj[0].x
                        r = proj[0].r
                        y = r_hydrogenic(r, l, n, alpha)
                        proj.add_projector(
                            newProjector(  # pylint: disable=unexpected-keyword-arg
                                x, y, l, j=ref_.j, label=addit_orb, alpha=alpha
                            )
                        )
                else:
                    alpha = fit_ortho_projectors(ref, n)
                    x = proj[0].x
                    r = proj[0].r
                    y = r_hydrogenic(r, l, n, alpha)
                    proj.add_projector(
                        newProjector(x, y, l, label=addit_orb, alpha=alpha)
                    )

        proj.to_file(
            root_dir / "external_projector" / pseudo_group_dir / f"{element}.dat"
        )
        for projector in proj:
            if spin_orbit:
                proj_ele.append(
                    {
                        "label": projector.label,
                        "l": projector.l,
                        "j": projector.j,
                        "alpha": projector.alpha,
                    }
                )
            else:
                proj_ele.append(
                    {
                        "label": projector.label,
                        "l": projector.l,
                        "alpha": projector.alpha,
                    }
                )
        projectors[element] = proj_ele
        with open(
            root_dir / "external_projector" / pseudo_group_dir / "projectors.json",
            "w",
            encoding="utf-8",
        ) as fp:
            # Output json file
            json.dump(projectors, fp, indent=2)


if __name__ == "__main__":
    main()
