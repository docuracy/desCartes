import subprocess
import os
import sys

subprocess.run(['conda', 'config', '--prepend', 'channels', 'conda-forge'])
subprocess.run(['conda', 'config', '--prepend', 'channels', 'ilastik-forge'])
subprocess.run(['conda', 'install', '-q', '-c', 'ilastik-forge', 'vigra', 'z5py', 'ndstructs', 'fastfilters', 'git'])

if not os.path.exists('./data'):
    os.makedirs('./data')

subprocess.run(['wget' '-q' 'https://descartes.docuracy.co.uk/ilastik/desCartes_preprocess.ilp' '-P' './data'])

# Install ilastik
subprocess.run(['wget', 'https://files.ilastik.org/ilastik-1.4.0-Linux.tar.bz2'])
subprocess.run(['tar', 'xjf', 'ilastik-1.4.0-Linux.tar.bz2'])
subprocess.run(['rm', './ilastik-1.4.0-Linux.tar.bz2'])
sys.path.append('/content/ilastik-1.4.0-Linux/lib/python3.7/site-packages')
