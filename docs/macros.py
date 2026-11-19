"""Numerical context shared by all walkthrough pages."""
import json
from pathlib import Path


def fmt(x, sig_or_decimals=6):
    """Integer -> significant digits; '.3f' -> fixed decimals; preserves signs."""
    if isinstance(x, bool):
        return 'yes' if x else 'no'
    if isinstance(x, str):
        return x
    if isinstance(sig_or_decimals, str):
        return format(x, sig_or_decimals)
    return format(x, f'.{sig_or_decimals}g')


def sci(x, significant=2):
    """Readable scientific notation in prose, tables and SVG (no LaTeX)."""
    if x == 0:
        return '0'
    mantissa, exponent = format(x, f'.{significant - 1}e').split('e')
    superscript = str(int(exponent)).translate(str.maketrans('-0123456789', '⁻⁰¹²³⁴⁵⁶⁷⁸⁹'))
    return f'{mantissa}×10{superscript}'


def define_env(env):
    env.variables['v'] = json.loads((Path(__file__).parent/'site/data/values.json').read_text())
    env.filters['fmt'] = fmt
    env.filters['sci'] = sci
    env.macro(fmt)
    env.macro(sci)
