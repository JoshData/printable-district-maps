# Generate printable maps for U.S. Congressional Districts.
# ------------------------------------------------------------------------------

# Start an Amazon EC2 instance using the latest MapBox
# AMI at http://mapbox.com/data. That's ami-1917fb70 at
# the time of writing. Note the availability zone.

# Create EBS volume for the Planet.OSM snapshot in the same
# availability zone.
# ec2addvol --snapshot snap-01406368 -z us-east-1d -K aws-pk.pem -C aws-cert.pem 
# http://mapbox.com/data/osm-planet

# The Tiger snapshot is missing form mapbox so we'll grab
# another for now.
# ec2addvol --snapshot snap-00fb0869 -z us-east-1d -K aws-pk.pem -C aws-cert.pem 

# You might find these or similar snapshots in the pull-down list
# in the AWS Console.

# Log in to the instance, and then get this file!
# svn co svn://razor.occams.info/viz/districtmaps .

# Attach the volumes to the instance and then mount them:
# mkdir /mnt/osm; mount -t ext3 /dev/sdf /mnt/osm
# mkdir /mnt/tiger; mount -t ext3 /dev/sdg /mnt/tiger

# Attach it to Postgres,  noting port number, which might have to be modified in the OSM file.
# pg_createcluster -d /mnt/osm/data 8.3 osm

# Give us access to the database because we don't know what the password is!
# edit /etc/postgresql/8.3/osm/pg_hba.conf and change the host local connection method from MD5 to trust.
# /etc/init.d/postgresql-8.3 restart

# Get the mapnik style information from OSM.
# svn export http://svn.openstreetmap.org/applications/rendering/mapnik

# Is there a better way to do this? Is there a snapshot with this?
# cd mapnik
# wget http://tile.openstreetmap.org/world_boundaries-spherical.tgz
# wget http://tile.openstreetmap.org/processed_p.tar.bz2
# wget http://tile.openstreetmap.org/shoreline_300.tar.bz2
# tar xzf world_boundaries-spherical.tgz
# tar xjf processed_p.tar.bz2 -C world_boundaries
# tar xjf shoreline_300.tar.bz2 -C world_boundaries

# To create a new osm.xml style file do this, but I've already customized
# the output so you probably don't want to overwrite it!
# python generate_xml.py osm.xml ../osm.xml --host localhost --port 5433 --dbname gis --user gis --password none

# Make a place for the output. We're probably almost out of the main partition's space.
# cd ..
# mkdir /mnt/maps
# ln -s /mnt/maps .

# Get district number locations because Mapnik's label placement method is not good for
# concave shapes! I've committed this file to the repository so there's no need to
# run this again, at least not till there's redistricting.
# wget -O - "http://www.govtrack.us/perl/wms/list-regions.cgi?dataset=http://www.rdfabout.com/rdf/usgov/congress/house/110&fields=coord&format=osm"        |sed "s|<tag k='URI' v='http://www.rdfabout.com/rdf/usgov/geo/us/\(..\)/cd/110/\(.*\)'/>|<tag k='state' v='\1'/><tag k='cd' v='\2'/>|" > district_numbers.osm

# Run this very script.
# python printablemaps.py [continue|GA11]
#    continue means generate maps for missing files, or specify a particular file like GA11 to recreate it 

# We'll put the maps into Amazon S3 for public downloading. First configure s3cmd with your credentials:
# s3cmd --configure
# Create a bucket? s3cmd mb s3://govtrackus --bucket-location=US
# Then upload: (take out --dry-run eventually)
# s3cmd sync --dry-run --delete-removed -M -P maps/ s3://govtrackus/printabledistrictmaps/

import sys
import os
import os.path
import math

from osgeo import ogr
import mapnik
import Image, ImageDraw, ImageFont, ImageEnhance

STATE_FIPS_TO_USPS = { 1: 'AL',  2: 'AK',  4: 'AZ',  5: 'AR',  6: 'CA',  8: 'CO',  9: 'CT',  10: 'DE',  11: 'DC',  12: 'FL',  13: 'GA',  15: 'HI',  16: 'ID',  17: 'IL',  18: 'IN',  19: 'IA',  20: 'KS',  21: 'KY',  22: 'LA',  23: 'ME',  24: 'MD',  25: 'MA',  26: 'MI',  27: 'MN',  28: 'MS',  29: 'MO',  30: 'MT',  31: 'NE',  32: 'NV',  33: 'NH',  34: 'NJ',  35: 'NM',  36: 'NY',  37: 'NC',  38: 'ND',  39: 'OH',  40: 'OK',  41: 'OR',  42: 'PA',  44: 'RI',  45: 'SC',  46: 'SD',  47: 'TN',  48: 'TX',  49: 'UT',  50: 'VT',  51: 'VA',  53: 'WA',  54: 'WV',  55: 'WI',  56: 'WY',  60: 'AS',  66: 'GU',  69: 'MP',  72: 'PR',  78: 'VI' }

STATE_TIGER_DIRS = ('01_ALABAMA',  '02_ALASKA',  '04_ARIZONA',  '05_ARKANSAS',  '06_CALIFORNIA',  '08_COLORADO',  '09_CONNECTICUT',  '10_DELAWARE',  '11_DISTRICT_OF_COLUMBIA',  '12_FLORIDA',  '13_GEORGIA',  '15_HAWAII',  '16_IDAHO',  '17_ILLINOIS',  '18_INDIANA',  '19_IOWA',  '20_KANSAS',  '21_KENTUCKY',  '22_LOUISIANA',  '23_MAINE',  '24_MARYLAND',  '25_MASSACHUSETTS',  '26_MICHIGAN',  '27_MINNESOTA',  '28_MISSISSIPPI',  '29_MISSOURI',  '30_MONTANA',  '31_NEBRASKA',  '32_NEVADA',  '33_NEW_HAMPSHIRE',  '34_NEW_JERSEY',  '35_NEW_MEXICO',  '36_NEW_YORK',  '37_NORTH_CAROLINA',  '38_NORTH_DAKOTA',  '39_OHIO',  '40_OKLAHOMA',  '41_OREGON',  '42_PENNSYLVANIA',  '44_RHODE_ISLAND',  '45_SOUTH_CAROLINA',  '46_SOUTH_DAKOTA',  '47_TENNESSEE',  '48_TEXAS',  '49_UTAH',  '50_VERMONT',  '51_VIRGINIA',  '53_WASHINGTON',  '54_WEST_VIRGINIA',  '55_WISCONSIN',  '56_WYOMING',  '60_AMERICAN_SAMOA',  '66_GUAM',  '69_COMMONWEALTH_OF_THE_NORTHERN_MARIANA_ISLANDS',  '72_PUERTO_RICO',  '78_VIRGIN_ISLANDS_OF_THE_UNITED_STATES')

STATE_NAMES = { "AL": "Alabama", "AK": "Alaska", "AS": "American Samoa",  "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FM": "Federated States of Micronesia", "FL": "Florida", "GA": "Georgia", "GU": "Guam", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MH": "Marshall Islands", "MD": "Maryland",  "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",  "ND": "North Dakota", "MP": "Northern Mariana Islands", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PW": "Palau", "PA": "Pennsylvania",  "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",  "VT": "Vermont", "VI": "Virgin Islands", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming" } 

# Another projection might be better but the scaling factor filters in
# osm.xml won't work if this is changed...
proj = "+proj=latlong +datum=WGS84"

def DrawMap(state_fips, state, district, shpfile, shpfeature, map_size, contextmap) :
	fctx = ""
	if contextmap :
		fctx = "_context"
	imgfile = 'maps/' + state + district + "_" + str(map_size) + fctx + '.png'
	if outputfilter == "continue" and os.path.exists(imgfile) :
		return

	if contextmap :
		map_size /= 6

	# Get bounding box of this map, which will be a little larger than the boudning box of the district.
	long_min,  long_max,  lat_min,  lat_max = shpfeature.GetGeometryRef().GetEnvelope()
	margin = 0.06
	if contextmap :
		margin = 1
	d_long = long_max-long_min
	d_lat = lat_max-lat_min
	long_min -= d_long*margin
	long_max += d_long*margin
	lat_min -= d_lat*margin
	lat_max += d_lat*margin
	
	# Choose a map aspect ratio, and then size.
	if d_long > d_lat * 2.5 : # two landscape sheets side by side
		map_width = int(2.58*map_size)
		map_height = 1*map_size
	elif d_lat > d_long * 2.5 : # two portrait sheets side by side
		map_width = 1*map_size
		map_height = int(2.58*map_size)
	elif d_long > d_lat * 1.1 : # landscape
		map_width = int(1.29*map_size) # aspect ratio of 8.5x11 sheet
		map_height = 1*map_size
	elif d_lat > d_long * 1.1 : # portrait
		map_width = 1*map_size
		map_height = int(1.29*map_size)
	else : # square
		map_width = map_size
		map_height = map_size
	
	# Create a map and add the basic map layer.
	m = mapnik.Map(map_width, map_height, proj)

	m.zoom_to_box(mapnik.Envelope(long_min, lat_min, long_max, lat_max))
	
	if not contextmap :
		m.background = mapnik.Color('steelblue')

		# Streets
		mapnik.load_map(m, 'osm.xml')
	
		# Add a layer for the places in the state.
		s = mapnik.Style()
		r = mapnik.Rule()
		t = mapnik.TextSymbolizer('NAME', 'DejaVu Sans Book', map_size/85, mapnik.Color('rgb(60%,30%,30%)'))
		t.halo_fill = mapnik.Color('white')
		t.halo_radius = 3
		r.symbols.append(t)
		s.rules.append(r)
		m.append_style('Places Style',s)
		lyr = mapnik.Layer('world', proj)
		lyr.datasource = mapnik.Shapefile(file=(shpfile % ('place')))
		lyr.styles.append('Places Style')
		m.layers.append(lyr)

		# Add a layer for the county subdivisions in the state.
		s = mapnik.Style()
		r = mapnik.Rule()
		t = mapnik.TextSymbolizer('NAME', 'DejaVu Sans Book', map_size/75, mapnik.Color('rgb(70%,20%,20%)'))
		t.halo_fill = mapnik.Color('white')
		t.halo_radius = 3
		r.symbols.append(t)
		s.rules.append(r)
		m.append_style('County Subdivisions Style',s)
		lyr = mapnik.Layer('world', proj)
		lyr.datasource = mapnik.Shapefile(file=(shpfile % ('cousub')))
		lyr.styles.append('County Subdivisions Style')
		m.layers.append(lyr)

		# Add a layer for the counties in the state.
		s = mapnik.Style()
		r = mapnik.Rule()
		t = mapnik.TextSymbolizer('NAME', 'DejaVu Sans Bold', int(map_size/60), mapnik.Color('rgb(70%,20%,20%)'))
		t.halo_fill = mapnik.Color('white')
		t.halo_radius = 3
		r.symbols.append(t)
		p = mapnik.LineSymbolizer(mapnik.Color('rgb(70%,20%,20%)'), map_size/400)
		p.stroke.opacity = .2 # has no effect
		p.stroke.add_dash(.1, .1) # has no effect
		r.symbols.append(p)
		s.rules.append(r)
		m.append_style('Counties Style',s)
		lyr = mapnik.Layer('world', proj)
		lyr.datasource = mapnik.Shapefile(file=(shpfile % ('county')))
		lyr.styles.append('Counties Style')
		m.layers.append(lyr)

	else :
		m.background = mapnik.Color('white')
	

	# Add a layer for the boundaries against other U.S. states.. We need two styles.
	# The first is a shaded style for other states. The second is an outline style
	# for all states including this one, to make sure we get the boundary with other
	# countries.
	s = mapnik.Style()
	r = mapnik.Rule()
	p = mapnik.PolygonSymbolizer(mapnik.Color('rgb(40%,40%,40%)')) # shading
	p.fill_opacity = .6
	r.symbols.append(p)
	r.filter = mapnik.Filter("[STATEFP] <> '" + state_fips + "'")
	s.rules.append(r)
	r = mapnik.Rule()
	r.symbols.append(mapnik.LineSymbolizer(mapnik.Color('rgb(50%,50%,50%)'), map_size/150)) # thick outline
	s.rules.append(r)
	m.append_style('States Style',s)
	lyr = mapnik.Layer('world', proj)
	lyr.datasource = mapnik.Shapefile(file="/mnt/tiger/TIGER2008/tl_2008_us_state.shp")
	lyr.styles.append('States Style')
	m.layers.append(lyr)

	# Add a layer for the boundary of this district against the others in this state. We'll
	# draw outlines and shading for the other districts, which is enough to give us the
	# boundary of this district (since the state boundary is already drawn).
	s = mapnik.Style()
	r = mapnik.Rule()
	if not contextmap :
		p = mapnik.PolygonSymbolizer(mapnik.Color('rgb(100%,100%,100%)'))
		p.fill_opacity = .8
		r.symbols.append(p)
		p = mapnik.LineSymbolizer(mapnik.Color('rgb(0%,0%,0%)'), map_size/300)
	else :
		p = mapnik.LineSymbolizer(mapnik.Color('rgb(0%,0%,0%)'), map_size/200)
	p.stroke.opacity = .2 # has no effect
	p.stroke.add_dash(12, 12) # has no effect
	r.symbols.append(p)
	if not contextmap :
		r.filter = mapnik.Filter("[CD110FP] <> '" + district + "'")
	s.rules.append(r)
	if contextmap :
		r = mapnik.Rule()
		p = mapnik.PolygonSymbolizer(mapnik.Color('rgb(100%,0%,0%)'))
		p.fill_opacity = .25
		r.symbols.append(p)
		r.filter = mapnik.Filter("[CD110FP] = '" + district + "'")
		s.rules.append(r)
	m.append_style('Other Districts Style',s)
	lyr = mapnik.Layer('world', proj)
	lyr.datasource = mapnik.Shapefile(file=(shpfile % ('cd110')))
	lyr.styles.append('Other Districts Style')
	m.layers.append(lyr)

	# Add a layer for district numbers using the point locations that I've computed for GovTrack's
	# district maps, since Mapnik places labels in weird locations for weird polygons.
	s = mapnik.Style()
	r = mapnik.Rule()
	if not contextmap :
		t = mapnik.TextSymbolizer('cd', 'DejaVu Sans Bold', int(map_size/30), mapnik.Color('black'))
	else :
		t = mapnik.TextSymbolizer('cd', 'DejaVu Sans Bold', int(map_size/17), mapnik.Color('black'))
	r.symbols.append(t)
	r.filter = mapnik.Filter("[state] = '" + state.lower() + "'")
	s.rules.append(r)
	m.append_style("District Numbers Style", s)
	lyr = mapnik.Layer("district_numbers", proj)
	lyr.datasource = mapnik.Osm(file='district_numbers.osm')
	lyr.styles.append('District Numbers Style')
	m.layers.append(lyr)

	mapnik.render_to_file(m, imgfile, 'png')
	
	# Post process the image.
	im = Image.open(imgfile)

	if not contextmap :
		# Add translucent bands for the title and footer.
		layer = Image.new('RGBA', im.size, (0,0,0,0))
		draw = ImageDraw.Draw(layer)
		draw.rectangle([ (0, 0), (map_width, map_size/25) ], fill="#555555")
		draw.rectangle([ (0, map_height - map_size/50), (map_width, map_height) ], fill="#555555")
		alpha = layer.split()[3]
		alpha = ImageEnhance.Brightness(alpha).enhance(.8)
		layer.putalpha(alpha)
		im = Image.composite(layer, im, layer)
		del draw 

		# Title text.
		title_a = STATE_NAMES[state] + u"\u2019s " + str(int(district))
		title_b = "  Congressional District"
		if int(district) % 100 in (11, 12, 13) :
			ordinal = "th"
		elif int(district) % 10 == 1 :
			ordinal = "st"
		elif int(district) % 10 == 2 :
			ordinal = "nd"
		elif int(district) % 10 == 3 :
			ordinal = "rd"
		else :
			ordinal = "th"
	
		font = ImageFont.truetype("/root/src/mapnik/fonts/dejavu-fonts-ttf-2.30/ttf/DejaVuSans-Bold.ttf", map_size/45)
		font2 = ImageFont.truetype("/root/src/mapnik/fonts/dejavu-fonts-ttf-2.30/ttf/DejaVuSans-BoldOblique.ttf", map_size/90, encoding="unic")
		title_a_width, title_a_height = font.getsize(title_a)
		title_width, title_height = font.getsize(title_a + title_b)
		ordinal_width, ordinal_height = font.getsize(ordinal)
		draw = ImageDraw.Draw(im)
		draw.text(((map_width-title_width)/2, 4 + ordinal_height/4), title_a + title_b, font=font)
		draw.text(((map_width-title_width)/2 + title_a_width - 2, 4 + ordinal_height/6), ordinal, font=font2)
		del draw 
	
		footer = "Map by www.GovTrack.us. Street data from OpenStreetMap.org. Reuse with attribution under CC-BY-SA 2.0."
		font = ImageFont.truetype("/root/src/mapnik/fonts/dejavu-fonts-ttf-2.30/ttf/DejaVuSans.ttf", map_size/70)
		footer_width, footer_height = font.getsize(footer)
		draw = ImageDraw.Draw(im)
		draw.text((map_width-footer_width-10, map_height - map_size/50+1), footer, font=font)
		del draw 

	else :
		draw = ImageDraw.Draw(im)
		draw.rectangle([ (0, 0), (map_width-1, map_height-1) ], outline="#000000")
		del draw 

	im.convert("RGB").save(imgfile, "PNG")

outputfilter = None
if len(sys.argv) > 1 :
	outputfilter = sys.argv[1]
		
for state in STATE_TIGER_DIRS :
	try :
		state_fips, state_name = state.split("_", 1)
		if not int(state_fips) in STATE_FIPS_TO_USPS :
			continue
	except :
		# Skip other files in the directory.
		continue
	shpfile = '/mnt/tiger/TIGER2008/' + state + '/tl_2008_' + state_fips + '_%s.shp'
	shp = ogr.Open(shpfile % ('cd110'),  False)
	layer = shp.GetLayer(0)
	for feature in layer :
		for size in (150*8, 150*16, 150*24) :
			state = STATE_FIPS_TO_USPS[int(state_fips)]
			district = feature.GetField("CD110FP")

			if district in ('00', '98', '99') :
				continue
			if outputfilter != None and outputfilter != "continue" and state + district + "_" + str(size) != outputfilter :
				continue

			print state, district, size
		
			# Draw PNG maps
			DrawMap(state_fips, state, district, shpfile, feature, size, False)
			DrawMap(state_fips, state, district, shpfile, feature, size, True)
			
			# Composite into a PDF
			im1 = Image.open('maps/' + state + district + "_" + str(size) + '.png')
			im2 = Image.open('maps/' + state + district + "_" + str(size) + '_context.png')
			im1.paste(im2, (5, size/25 + 5) )
			im1.save('maps/' + state + district + "_" + str(size) + '.pdf', "PDF")
