# Print-Quality Congressional District Maps

This script generates high-resolution United States congressional district maps
from U.S. Census TIGER/Line shapefiles and Open Street Map (OSM) road data.

The OSM data is huge, and that's what makes this difficult. We'll load it into
an Amazon RDS Postgres database. Then we use Mapnik and TileMill to render the images.

I first did this in early 2010, but thanks to redistricting those maps went out
of date after only a year and a half. I also used Census and OSM data that was
pre-loaded into Amazon AWS by Mapbox, but they aren't providing current data
in that way anymore. See my original post at:
http://razor.occams.info/blog/2010/02/26/printable-congressional-district-maps-behind-the-scenes/.

## Launch an AWS RDS instance

Log into your Amazon AWS management console and launch a new Postgres RDS instance.

Since we'll generate the maps once and then shut the instance down, we'll ask for an
expensive high-powered instance type. (Current pricing $0.672/hr and $0.125 per GB-month.)

The whole planet-wide OSM data is probably 400 GB+ in a database. The U.S. data
is only about 18 GB.

	DB Instance Class: db.m1.xlarge
	Multi-AZ Deployment: no
	Allocated Storage: 20 GB
	DB Instance Idnetifier: osm-db
	Master Username: root
	Master Password: password
	(second page...)
	Database Name: osm
	Database Port: 5432
	Availability Zone: Doesn't matter, but remember what you choose.
	(third page...)
	Enabled Automatic Backups: no

We'll make the RDS instance available to (and only to) our EC2 instance in a moment.

## Launch an AWS EC2 Instance

Start a new EC2 instance.

	AMI: Ubuntu Server 13.10 64bit - ami-ad184ac4
	Instance Type: m1.large
	Availability Zone: Same as above

The instance will have a small volume mounted at the root and also a big 400 GB
*ephemeral* volume mounted at /mnt.

In the EC2 console, find the new instance and look for its security group. If AWS
made one for you, it might be `launch-wizard-1`. Remember what it is. Now go back
to the RDS control panel. Look for the RDS instance's security group. It is probably
`default`. Click it to edit the security group, and then click the edit icon to edit
the group. Change `CIDR/IP` to `EC2 Security Group`, choose the EC2 security group
that you are remembering, and click Add.

Now go back to the RDS console and find the Endpoint. It's something like
`osm-db.cdebjzhnrxok.us-east-1.rds.amazonaws.com:5432`. Copy that somewhere --- we'll
need it in a moment.

## Prepare the system

Log into your EC2 machine with SSH.

Much of the instructions below is based on https://www.mapbox.com/tilemill/docs/guides/osm-bright-ubuntu-quickstart/.

Install some system packages:

	sudo apt-get update
	sudo apt-get install unzip git \
		postgresql-client-common postgresql-9.1-postgis \
		build-essential python-dev python-pip protobuf-compiler \
		libprotobuf-dev libtokyocabinet-dev python-psycopg2 libgeos-c1 \
		python-pillow python-gdal python-mapnik python-mpmath fonts-sil-gentium
	sudo pip install imposm

Install tilemill:

	wget -O- http://tilemill.s3.amazonaws.com/latest/install-tilemill.tar.gz | tar -zxO | sudo bash

Get OSM Bright, which contains OSM-to-Postgres import logic and map styling.

	git clone https://github.com/mapbox/osm-bright

Get the repository containing this README file:

	git clone https://github.com/JoshData/printable-district-maps

So that we don't get confused and use the wrong database by accident, turn off the local database. We installed it to get some configuration files for PostGIS but don't actually need the running server since we're using RDS.

	sudo service postgresql stop

## Download data

Download OSM data in PBF format for the United States. Geofabrik's mirror (http://download.geofabrik.de/north-america.html) has U.S. data broken down into five files. You'll also need some other general GIS data.

	sudo chown ubuntu.ubuntu /mnt
	ln -s /mnt/ data
	cd data
	wget http://download.geofabrik.de/north-america/us-midwest-latest.osm.pbf
	wget http://download.geofabrik.de/north-america/us-northeast-latest.osm.pbf
	wget http://download.geofabrik.de/north-america/us-pacific-latest.osm.pbf
	wget http://download.geofabrik.de/north-america/us-south-latest.osm.pbf
	wget http://download.geofabrik.de/north-america/us-west-latest.osm.pbf
	wget http://tilemill-data.s3.amazonaws.com/osm/coastline-good.zip
	wget http://tilemill-data.s3.amazonaws.com/osm/shoreline_300.zip
	wget http://mapbox-geodata.s3.amazonaws.com/natural-earth-1.3.0/physical/10m-land.zip
	wget http://www2.census.gov/geo/tiger/TIGER2013/CD/tl_2013_us_cd113.zip
	wget http://www2.census.gov/geo/tiger/TIGER2013/COUNTY/tl_2013_us_county.zip
	wget http://www2.census.gov/geo/tiger/TIGER2013/ZCTA5/tl_2013_us_zcta510.zip
	for x in *.zip; do unzip $x; done
	cd ..

It is 5 GB in all, so it will take at least 10 minutes to get it, or more if the servers
are being slow.

## Setup Postgres

Put your RDS info into environment variables:

	export HOST=osm-db.cdebjzhnrxok.us-east-1.rds.amazonaws.com
	export PORT=5432

The run:

	echo "CREATE EXTENSION postgis;" | psql -h $HOST -p $PORT -U root -d osm 
	psql -h $HOST -p $PORT -U root -d osm -f /usr/share/postgresql/9.1/contrib/postgis-1.5/postgis.sql
	psql -h $HOST -p $PORT -U root -d osm -f /usr/share/postgresql/9.1/contrib/postgis-1.5/spatial_ref_sys.sql

Enter the password `password` each time.

There's some worrisome output, especially on the third command. Not sure what to do about it.

## Alterate: Setup Postgres as a Local Database

Here are some instructions for running Postgres inside the EC2 instance instead of
in a separate RDS instance. Skip this section unless you don't like RDS.

TOOD: Move the database into the /mnt volume where it will have more room.

Start by giving yourself access to your database:

	sudo nano /etc/postgresql/9.1/main/pg_hba.conf

Change the `local` and `host` lines toward the end to have their login methods be `trust` so that you can access the database from within this machine without worrying about passwords. Those lines should look like:

	local   all             postgres                                trust
	local   all             all                                     trust
	host    all             all             127.0.0.1/32            trust
	host    all             all             ::1/128                 trust

Save and exit from nano with Ctrl-O then Ctrl-X. Then continue:

	sudo /etc/init.d/postgresql restart

	psql -U postgres -c "create database osm;"
	psql -U postgres -d osm -f /usr/share/postgresql/9.1/contrib/postgis-1.5/postgis.sql
	psql -U postgres -d osm -f /usr/share/postgresql/9.1/contrib/postgis-1.5/spatial_ref_sys.sql

There's a lot of output like `DROP TABLE` and `INSERT`. If it doesn't look like an error, you're OK.

## Load the data into the database

Start the process of loading the OSM files into Postgres:

	imposm --connection=postgis://root:password@$HOST:$PORT/osm \
		-m osm-bright/imposm-mapping.py \
		--proj=EPSG:4326 --cache-dir=data -c 8 \
    	--read --write --optimize --deploy-production-tables data/*.osm.pbf

This will take 9 hours.

The first hour and a half is pre-processing the files, which generates a few gigabytes of
cache files. The next 6 hours is loading the data into Postgres. And the last 1.5 hours is
optimizing the tables.

## Setup TileMill

Prepare OSM Bright's configuration:

	cp osm-bright/configure.py.sample osm-bright/configure.py 

We'll need to edit the configuration to make it work for us. You'll need to change:

* importer to `imposm`
* database connection info
* paths to the three ZIP files we downloaded earlier (which contain shapefiles), e.g. `path.join(getcwd(),"../data/coastline-good.zip")`

The configuration file I used is in `osm-bright/configure.py`. You'll at least need to change the
database hostname and copy the file into the right place.

Now run OSM Bright to generate the TileMill configuration:

	mkdir -p ~/Documents/MapBox/project
	cd osm-bright
	./make.py
	cd ..

Sorry but I did something weird earlier. In the `imposm` step, I had it load the geometry in
the WGS84 projection rather than the default Spherical Mercator projection. OSM Bright
assumes it was the default, so we'll need to fix that.

	python printable-district-maps/fix_srs.py Documents/MapBox/project/OSMBright/project.mml

# Test an image

Run the TileMill export command to make a test image based on the OSM Bright project:

	rm -f test.jpeg
	/usr/share/tilemill/index.js export OSMBright test.jpeg --format=jpeg --bbox=-77.1408,38.7790,-76.893,39.0088 --static_zoom=17 --width=3000 --height=3000

You'll get `test.jpeg` in the current directory showing a high-resolution road map of Washington, DC. Check that it looks good. You'll need to copy the file off of this machine to your local computer.

# Generating maps

Start the TileMill tile server:

	/usr/share/tilemill/index.js tile

It listens on port 20008 on localhost. You can run the next step from another machine, but if you do you'll have to set up port forwarding or change TileMill's configuration to listen on a public address.

In another console, run the map-generating script:

	python printable-district-maps/printablemaps.py data

