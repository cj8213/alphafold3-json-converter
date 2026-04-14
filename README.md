# AlphaFold 3 JSON Converter

AlphaFold 3 Web Server exports often crash Local Installations due to formatting mismatches (specifically around `seeds` formatting and `smiles` to `ccdCodes` mapping for ligands). 

This lightweight Python script automatically normalizes your server exports to meet local requirements. 

**Usage:**
`python af3_convert.py your_server_export.json`
