## FAQ 
### What's this?
**Fulgence** is a text-based railroad simulator that will let you perform various tasks:
- [x] define realistic or fancy routes
- [x] define realistic or fancy schedules
- [ ] define rolling stock (only EMUs for now)
- [ ] distribute train services over mutiple simulation engines if you have a busy train schedule (only single sim engine for now)
- [x] run schedules in real-time or accelerated time
- [ ] trainspot at a platform instantly, check out its real-time information board
- [ ] calibrate/optimize trains frequency at peak and off peak hours
- [x] calculate power consumption
- [x] get detailed statistics for data crunching and rendering
- [ ] access the route control room

### Notes for route designers
#### Layout
- routes will support both on-track signals and electronic signals (only on-track for now) for trains separation
- Routes are located in (Fulgence folder)/(routeName)/ 
- Routes are made of segments located in (routeName)/segments/(segmentName)/. For example: ParisLine1/segments/WestboundMain/ for the default route
- A segment is a set of contiguous blocks where each block is under control of a signal
- Blocks are not explicitely delimited or managed in Fulgence. In fact, signals define blocks.
- Blocks are unidirectional, except the ones protected by a **reversing signal** 
- In each segment, you need to describe the location of signals (SIGs), stations (STAs), speed limits (TIVs) and grades (GRDs). 
- All route and schedule data are kept in simple text files. Lines beginning with a hash are ignored, as one would expect.
- Markers are not supported yet. In the pipe: tunnels (provide weather protection), country boundaries (with imperial/metric unit changes), points of interest (landmarks), areas of interest, platform names, substations (for line sectioning).
- Weather is not supported yet
- Only passenger stations are available at the moment. Water points and fuel stations (coal or diesel) will be added later.
#### Signalling guide
The following on-track signals are or will be implemented:
- [x]  *Type 1*: this is the usual 3-aspect signal. The possible states are: VL (green, all clear), A (yellow, prepare to stop at next signal) and C (red, impassable stop).
- [x] *Type 2*: this is a buffer signal that allows reversing to a segment which is different from the origin segment. As far as the origin segment is concerned, its only possible state is C (red, impassable). As for the first signal in the reversed direction, it is controlled by a type 5 signal.
- [x] *Type 3*: this is a 2-aspect signal (A and C). It  must always **precede** a type 2 or 4D, as its state depends on the switch position in the upcoming junction.
- [ ] *Type 4D*: this is a diverging junction signal, used to stitch segments together. Both legs of the junction see trains **moving in the same direction**. (As opposed to the second type of diverging junction described below).
- [ ] *Type 4C*: this is a converging junction signal, used to stitch segments together. Both legs of the junction see trains **moving in the same direction**.
- [x] *Type 5*: this is a diverging junction signal for trains coming from a reversing block. It must always **be preceded** by a type 2 signal. One leg of the junction is for trains **coming from** the forward direction, the other leg is for trains **going to** the reverse direction.

Junction signals can manage only two legs, no less, no more. One leg is the main segment (left or right), the other one to the diverging/converging segment (left or right).Junction signals must have a unique name in both segments so that the engine may perform the segments stitching properly.

### Requirements
#### Single and multi simulation engines
- Python 2.7
- A redis server running on the localhost (apt-get install redis-server in Ubuntu). Redis is used for signal aspects real-time management.
#### Multi simulation engines
- taskset (part of utils-linux in Ubuntu).
Note: when using multi simulation engines, redis is also used for inter-process synchronisation.
#### Control room
Note: control room relies on redis for getting the real-time state of a train.

### Let's get started
To run the simulation in single simulation engine mode, simply run mp.py without arguments. What happens then is that the engine (mp.py) starts the default schedule of the default route, the Paris Metro line 1, located in ParisLine1/schedules/default.txt

By default, 50 train services are run in parallel. The sim will not stop until you hit CTRL+C

### Parameters
To run the sim in realtime, set REALTIME constant to True. Otherwise it will run as fast as possible on your CPU.

To adjust simulation precision, you may set the CYCLE variable to your wishing. I recommend to keep the default value to get the best trade off between precision and speed of execution though. 

To run the sim in debug mode, modify the first line to add the -O option to python

### Command line options
Fulgence will run fine without options, but there are several things you may wish to change:
- Set a given duration (in seconds) using *mp.py --duration=seconds*, otherwise the sim will go on forever.
- Pick a non-default route (the TestTrack route for instance) with *mp.py --route=TestTrack*
- Choose a non-default schedule: *mp.py --schedule=myschedule.txt*
- Enable real time: *mp.py --realtime*
#### Examples
- Run in real time for 1 hour: *mp.py --realtime --duration=3600*
