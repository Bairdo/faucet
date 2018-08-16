source venv/bin/activate
pip3 install .
python3 -m pytest --cov=chewie/ --cov-report term --cov-report=xml:coverage.xml test/