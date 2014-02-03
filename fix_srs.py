#!/usr/bin/python
import sys, json

D = json.load(open(sys.argv[1]))
for layer in D["Layer"]:
	if layer["Datasource"].get("type") != "postgis": continue
	layer["srs"] = "+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs"
	layer["srs-name"] = "4326"
	layer["Datasource"]["srs"] = "+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs"
	layer["Datasource"]["srs-name"] = "4326"
with open(sys.argv[1], "w") as f:
	json.dump(D, f, indent=2)


