c hypoDD.inc: Stores parameters that define array dimensions in hypoDD.
c             Modify to fit size of problem and available computer memory.
c             If 3D raytracing is used, also set model parameters in vel3d.inc.
c Parameter Description:
c MAXEVE:   Max number of events (must be at least the size of the number
c           of events listed in the event file).
c MAXDATA:  Max number of observations (must be at least the size of the
c           number of observations).
c MAXEVE0:  Max number of events used for SVD. If only LSQR is used,
c           MAXEVE0 can be set to 2 to free up memory.
c MAXDATA0: Max number of observations used for SVD. If only LSQR is used,
c           MAXDATA0 can be set to 1 to free up memory.
c MAXLAY:   Max number of model layers.
c MAXSTA:   Max number of stations.
c MAXCL:    Max number of clusters allowed.
c
c Select hypodd.dimensions.mode in user_configuration/config.yaml:
c   auto   - the workflow replaces calculated values and reads MAXEVE0,
c            MAXLAY, and MAXCL from user_configuration/config.yaml.
c   manual - the workflow activates the MANUAL block below. Edit all values.
c The template itself is never changed during a workflow run. The effective
c file used for compilation is written to the HypoDD run directory.

	integer*4 MAXEVE, MAXLAY, MAXDATA, MAXSTA, MAXEVE0, MAXDATA0
	integer*4 MAXCL

c BEGIN AUTO PARAMETERS
      parameter(MAXEVE=   {{MAXEVE}},
     &          MAXDATA=  {{MAXDATA}},
     &          MAXEVE0=  {{MAXEVE0}},
     &          MAXDATA0= {{MAXDATA0}},
     &          MAXLAY=   {{MAXLAY}},
     &          MAXSTA=   {{MAXSTA}},
     &          MAXCL=    {{MAXCL}})
c END AUTO PARAMETERS

c BEGIN MANUAL PARAMETERS
c      parameter(MAXEVE=   6500,
c     &          MAXDATA=  3000000,
c     &          MAXEVE0=  215,
c     &          MAXDATA0= 100000,
c     &          MAXLAY=   50,
c     &          MAXSTA=   400,
c     &          MAXCL=    200)
c END MANUAL PARAMETERS
