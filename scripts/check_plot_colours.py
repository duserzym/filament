"""Audit token luminance under Machado et al. (2009), severity 1.0.

Matrices act on linear sRGB; clip before measuring relative luminance.
Reference: https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html
Run: env -u PYTHONPATH .venv/bin/python scripts/check_plot_colours.py
"""
import json

import numpy as np

from rawtims_gui.plot_palette import PALETTES
from rawtims_gui.studio.theme import theme_color

MATRICES = {
    'protanopia': np.array([[.152286, 1.052583, -.204868],
                           [.114503, .786281, .099216],
                           [-.003882, -.048116, 1.051998]]),
    'deuteranopia': np.array([[.367322, .860646, -.227968],
                            [.280085, .672501, .047413],
                            [-.011820, .042940, .968881]]),
}


def linear_rgb(token):
    color = theme_color(token)
    rgb = np.array([color.redF(), color.greenF(), color.blueF()])
    return np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)


def contrast(a, b):
    a, b = sorted([float(a @ [.2126, .7152, .0722]), float(b @ [.2126, .7152, .0722])])
    return (b + .05) / (a + .05)


def audit():
    result = {}
    for theme, plot in PALETTES.items():
        result[theme] = {}
        for name, matrix in MATRICES.items():
            included, excluded, background, halo = [np.clip(matrix @ linear_rgb(value), 0, 1)
                for value in (plot.included, plot.excluded, plot.background, plot.pointHalo)]
            result[theme][name] = {
                'included_vs_excluded': round(contrast(included, excluded), 3),
                'included_vs_background': round(contrast(included, background), 3),
                'excluded_vs_background': round(contrast(excluded, background), 3),
                'included_vs_halo': round(contrast(included, halo), 3),
                'excluded_vs_hollow_center': round(contrast(excluded, background), 3),
            }
    return result


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
