# -*- coding: utf-8 -*-
#
# apt-get install python-gdal python-mapnik python-mpmath

import sys
import os
import os.path
import math
import mpmath
import urllib

from osgeo import ogr, osr
import mapnik
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# For output, convert numeric FIPS codes for U.S. states to their usual USPS abbreviations and names.
STATE_FIPS_TO_USPS = { 1: 'AL',  2: 'AK',  4: 'AZ',  5: 'AR',  6: 'CA',  8: 'CO',  9: 'CT',  10: 'DE',  11: 'DC',  12: 'FL',  13: 'GA',  15: 'HI',  16: 'ID',  17: 'IL',  18: 'IN',  19: 'IA',  20: 'KS',  21: 'KY',  22: 'LA',  23: 'ME',  24: 'MD',  25: 'MA',  26: 'MI',  27: 'MN',  28: 'MS',  29: 'MO',  30: 'MT',  31: 'NE',  32: 'NV',  33: 'NH',  34: 'NJ',  35: 'NM',  36: 'NY',  37: 'NC',  38: 'ND',  39: 'OH',  40: 'OK',  41: 'OR',  42: 'PA',  44: 'RI',  45: 'SC',  46: 'SD',  47: 'TN',  48: 'TX',  49: 'UT',  50: 'VT',  51: 'VA',  53: 'WA',  54: 'WV',  55: 'WI',  56: 'WY',  60: 'AS',  66: 'GU',  69: 'MP',  72: 'PR',  78: 'VI' }
STATE_NAMES = { "AL": "Alabama", "AK": "Alaska", "AS": "American Samoa",  "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FM": "Federated States of Micronesia", "FL": "Florida", "GA": "Georgia", "GU": "Guam", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MH": "Marshall Islands", "MD": "Maryland",  "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",  "ND": "North Dakota", "MP": "Northern Mariana Islands", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PW": "Palau", "PA": "Pennsylvania",  "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",  "VT": "Vermont", "VI": "Virgin Islands", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming" } 

# For rending the map title and footer, paths to a regular, bold, and bold-italic font:
font_path = "/usr/share/fonts/truetype/"
fonts = (font_path + "gentium/GenR102.ttf",
	     font_path + "gentium/GenAR102.ttf",
	     font_path + "gentium/GenAI102.ttf")

# For mapnik labels.
mapnik_label_font = 'DejaVu Sans Book'

# The projection, web mercator, which is necessary because the base map tiles
# are in this projection.
output_projection = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null +wktext +over +no_defs"

# The projection in which the Census shapefiles are stored, from the .prj file.
# It's basically WGS84, but perhaps not exactly? I'm not sure, but this is what
# the Census says it is.
census_shapefile_projection = "+proj=longlat +ellps=GRS80 +datum=NAD83 +no_defs"

# For getting the steet map tiles.
tile_size = 256
tile_baseurl = "http://localhost:20008/tile/OSMBright"
 #cloudmate_api_key, cloudmate_style = os.environ["CLOUDMATE"].split(":")		
 #tile_baseurl = "http://b.tile.cloudmade.com/%s/%s@2x/%d" % (cloudmate_api_key, cloudmate_style, tile_size)

def draw_district_outline(statefp, state, district, shpfeature, map_size, contextmap) :
	# Create an image with district outlines and shading over the parts of the map
	# in other districts or other states. Also compute our desired bounding box.

	# Get bounding box of this map, which will be a little larger than the boudning box of the district.
	long_min, long_max, lat_min, lat_max = shpfeature.GetGeometryRef().GetEnvelope()
	margin = 0.06
	if contextmap :
		margin = 1.5
	d_long = long_max-long_min
	d_lat = lat_max-lat_min
	long_min -= d_long*margin
	long_max += d_long*margin
	lat_min -= d_lat*margin
	lat_max += d_lat*margin

	# Choose an aspect ratio for the final image that is a good match for
	# the shape of the district. We have two choices. We could use nice-looking
	# aspect ratios or we could use aspect ratios that match common sizes of
	# paper so that the map can be printed nicely.
	good_aspect_ratios = [
		(3.0,    3.0/1.0), # 8.5x17 tabloid landscape
		(1.5,   16.0/9.0), # HD widescreen
		(1.25,  11.0/8.5), # 8.5x11 letter landscape
		(1/1.25, 1.0/1.0), # square
		(1/1.5,  8.5/11.0), # 8.5x11 letter portrait
		(0,      8.5/17.0), # 8.5x17 tabloid portrait
		]

	for threshold, ratio in good_aspect_ratios:
		if d_long/d_lat > threshold:
			if ratio > 1.0:
				map_width = int(ratio * map_size)
				map_height = map_size
			else:
				map_width = map_size
				map_height = int(map_size / ratio)
			break
	
	# Create a map.
	m = mapnik.Map(map_width, map_height, output_projection)

	# Center to the projected coordinates.
	bounds = (mapnik.Projection(output_projection).forward( mapnik.Projection(census_shapefile_projection).inverse(mapnik.Coord(long_min, lat_min)) ),
			mapnik.Projection(output_projection).forward( mapnik.Projection(census_shapefile_projection).inverse(mapnik.Coord(long_max, lat_max)) ))
	m.zoom_to_box(mapnik.Envelope(bounds[0].x, bounds[0].y, bounds[1].x, bounds[1].y))

	if not contextmap :
		# Add a layer for counties and ZCTAs.
		# TODO: These should really be generated with the map tile layer
		# so that the labels don't hit each other.
		for layer, featurename, labelfontsize, labelcolor in (
				("county", "NAME", map_size/40, mapnik.Color('rgb(70%,20%,20%)')),
				("zcta510", "ZCTA5CE10", map_size/60, mapnik.Color('rgb(40%,40%,80%)')),
				):
			s = mapnik.Style()
			r = mapnik.Rule()
			#p = mapnik.LineSymbolizer(labelcolor, map_size/300)
			#p.stroke.opacity = .3
			#p.stroke.add_dash(.1, .1)
			#r.symbols.append(p)
			r.symbols.append(mapnik.TextSymbolizer(mapnik.Expression('[%s]' % featurename), mapnik_label_font, labelfontsize, labelcolor))
			s.rules.append(r)
			m.append_style('%s Style' % layer, s)
			lyr = mapnik.Layer('world', census_shapefile_projection)
			lyr.datasource = mapnik.Shapefile(file="/home/user/data/gis/tl_2013_us_%s.shp" % layer)
			lyr.styles.append('%s Style' % layer)
			m.layers.append(lyr)


	# Draw shading and numbering for the other districts.
	district_outline_color = mapnik.Color('rgb(100%,75%,25%)')
	s = mapnik.Style()
	r = mapnik.Rule()
	p = mapnik.PolygonSymbolizer(mapnik.Color('rgb(70%,70%,70%)'))
	p.fill_opacity = .55
	r.symbols.append(p)
	r.filter = mapnik.Filter("([CD113FP] <> '" + district + "' || [STATEFP] <> '" + statefp + "') && [CD113FP] != 'ZZ'")
	t = mapnik.TextSymbolizer(mapnik.Expression('[CD113FP]'), mapnik_label_font, map_size/15, district_outline_color)
	t.halo_radius = map_size/120
	r.symbols.append(t)
	s.rules.append(r)

	# Draw the outlines of districts. Use a hard thin outline to be exact plus
	# a faded wider outline for strength.
	r = mapnik.Rule()
	p = mapnik.LineSymbolizer(district_outline_color, 2)
	r.symbols.append(p)
	p = mapnik.LineSymbolizer(district_outline_color, map_size/140)
	p.stroke.opacity = .35
	r.symbols.append(p)
	s.rules.append(r)

	m.append_style('Other Districts Style',s)
	lyr = mapnik.Layer('world', census_shapefile_projection)
	lyr.datasource = mapnik.Shapefile(file="/home/user/data/gis/tl_2013_us_cd113.shp")
	lyr.styles.append('Other Districts Style')
	m.layers.append(lyr)

	im = mapnik.Image(map_width, map_height)
	mapnik.render(m, im)

	env = m.envelope()
	env = ( mapnik.Projection(output_projection).inverse(mapnik.Coord(env[0], env[1])), mapnik.Projection(output_projection).inverse(mapnik.Coord(env[2], env[3])) )
	return im, env
	
def add_header_footer(filename):
	# Post process the image.
	im = Image.open(filename)
	im = im.convert("RGBA")

	# Add bands for the title and footer.
	draw = ImageDraw.Draw(im)
	draw.rectangle([ (0, 0), (im.size[0], min(im.size)/15) ], fill="#555555")
	draw.rectangle([ (0, im.size[1] - min(im.size)/50), im.size ], fill="#555555")

	# Title text.
	title_a = "The " + str(int(district))
	title_b = "   Congressional District of " + STATE_NAMES[state] + " (2013)"
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

	font = ImageFont.truetype(fonts[1], min(im.size)/25)
	font2 = ImageFont.truetype(fonts[2], min(im.size)/50, encoding="unic")
	title_a_width, title_a_height = font.getsize(title_a)
	title_width, title_height = font.getsize(title_a + title_b)
	ordinal_width, ordinal_height = font.getsize(ordinal)
	draw = ImageDraw.Draw(im)
	draw.text(((im.size[0]-title_width)/2, 4 + ordinal_height/4), title_a + title_b, font=font)
	draw.text(((im.size[0]-title_width)/2 + title_a_width - 2, 4 + ordinal_height/6), ordinal, font=font2)
	del draw 

	footer = u"Copyright © 2014 Civic Impulse, LLC (GovTrack.us). Data from OpenStreetMap.org; U.S. Census Bureau."
	font = ImageFont.truetype(fonts[0], min(im.size)/100)
	footer_width, footer_height = font.getsize(footer)
	draw = ImageDraw.Draw(im)
	draw.text((im.size[0]-footer_width-10, im.size[1] - min(im.size)/60), footer, font=font)
	del draw 

	im.convert("RGBA").save(filename, "PNG")

def post_process_thumbnail(filename):
	im = Image.open(filename)
	im = im.convert("RGBA")
	draw = ImageDraw.Draw(im)
	draw.rectangle([ (0, 0), (im.size[0]-1, im.size[1]-1) ], outline="#000000")
	del draw 
	im.save(filename, "PNG")

def tile_from_coord(lng, lat, zoom):
	n = 2**zoom
	xtile = ((lng + 180.0) / 360.0) * n
	ytile = (1.0 - (math.log(math.tan(lat*math.pi/180.0) + mpmath.sec(lat*math.pi/180.0)) / math.pi)) / 2.0 * n
	return int(xtile), int(ytile), xtile-int(xtile), ytile-int(ytile)

def add_osm_tiles(filename, bounds):
	im1 = Image.open(filename)
	composite = Image.new('RGBA', im1.size, (0,0,0,0))

	# What zoom level should we use? And then how much do we need to scale the tiles
	# to match the actual resolution of the output image? Because map labels are small
	# at high resolution, we'd rather use a lower zoom level and then resize the image
	# to make it larger than the other way.
	zoom_level = int(math.log(360 / (max((bounds[1].x-bounds[0].x)/im1.size[0], (bounds[1].y-bounds[0].y)/im1.size[1]) * tile_size)) / math.log(2) + 0.5)
	tile_scale = (360.0 / (2**zoom_level) / tile_size) / ((bounds[1].x-bounds[0].x)/im1.size[0])
	if tile_scale > 1.4: raise ValueError("Scale error, got upscaling: %f" % tile_scale) 
	if tile_scale < .66: raise ValueError("Scale error, got large downscaling: %f" % tile_scale) 

	# Fetch all of the tiles we need and lay them into place.
	t1 = tile_from_coord(bounds[0].x, bounds[1].y, zoom_level)
	t2 = tile_from_coord(bounds[1].x, bounds[0].y, zoom_level)
	for xtile in xrange(t1[0], t2[0]+2):
		for ytile in xrange(t1[1], t2[1]+2):
			# Get the tile from the tile server...
			fn = "tiles/%d-%d-%d.png" % (zoom_level, xtile, ytile) 
			if not os.path.exists(fn):
				url = "%s/%d/%d/%d.png" \
					% (tile_baseurl, zoom_level, xtile, ytile)
				print url
				img = urllib.urlopen(url).read()
				with open(fn, "w") as f:
					f.write(img)

			# Composite it into the right place.
			tile = Image.open(fn)
			tile = tile.resize((int(tile.size[0]*tile_scale), int(tile.size[1]*tile_scale)), Image.BICUBIC if tile_scale > 1 else Image.ANTIALIAS)
			composite.paste(tile,
				(-int(t1[2]*tile.size[0]) + (xtile-t1[0])*tile.size[0],
				 -int(t1[3]*tile.size[1]) + (ytile-t1[1])*tile.size[1] ) )

	composite = Image.alpha_composite(composite, im1)
	composite.save(filename, "png")

outputfilter = None
if len(sys.argv) > 1 :
	outputfilter = sys.argv[1]

if not os.path.exists("maps"): os.mkdir("maps")
if not os.path.exists("tiles"): os.mkdir("tiles")

shpfile = '/home/user/data/gis/tl_2013_us_cd113.shp'
shp = ogr.Open(shpfile, False)
layer = shp.GetLayer(0)
for feature in layer :
	state = STATE_FIPS_TO_USPS[int(feature.GetField("STATEFP"))]
	district = feature.GetField("CD113FP")

	#if district in ('00', '98', '99') :
	#	continue
	if outputfilter != None and not (state + district).startswith(outputfilter):
		continue

	print state, district

	size = 3072

	# Draw PNG map
	im, bounds = draw_district_outline(feature.GetField("STATEFP"), state, district, feature, size, False)
	im.save("/tmp/main.png", 'png256')
	add_header_footer("/tmp/main.png")
	add_osm_tiles('/tmp/main.png', bounds)
	im1 = Image.open('/tmp/main.png')

	# Draw the context map.
	im, bounds2 = draw_district_outline(feature.GetField("STATEFP"), state, district, feature, size/6, True)
	im.save("/tmp/context.png", 'png256')
	post_process_thumbnail("/tmp/context.png")
	add_osm_tiles('/tmp/context.png', bounds2)
	im2 = Image.open('/tmp/context.png')

	# Composite everything together.
	if not os.path.exists('maps/%d' % size): os.mkdir('maps/%d' % size)
	composite = Image.new("RGBA", im1.size)
	composite.paste(im1, (0, 0) )
	composite.paste(im2, (int(min(im1.size)/15 * 0.5), int(min(im1.size)/15 * 1.5)) )
	fn = 'maps/%d/%s%s.png' % (size, state, district)
	composite.save(fn, "png")
	print "Saved", fn
