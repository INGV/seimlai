c ph2dt.inc: Stores parameters that define array dimensions in ph2dt.
c            Modify to fit size of problem and available computer memory.
c Parameter Description:
c MEV:   Max number of events.
c MSTA:  Max number of stations.
c MOBS:  Max number of phases (P&S) per event.
c
c Select hypodd.dimensions.mode in user_configuration/config.yaml:
c   auto   - the workflow replaces the values in the AUTO block.
c   manual - the workflow activates the MANUAL block below. Edit its values.
c The template itself is never changed during a workflow run. The effective
c file used for compilation is written to the HypoDD run directory.

	integer	MEV, MSTA, MOBS

c BEGIN AUTO PARAMETERS
	parameter(MEV=    {{MEV}},
     &		MSTA=   {{MSTA}},
     &		MOBS=   {{MOBS}})
c END AUTO PARAMETERS

c BEGIN MANUAL PARAMETERS
c	parameter(MEV=    12000,
c     &		MSTA=   2600,
c     &		MOBS=   1000)
c END MANUAL PARAMETERS
