# The MIT License (MIT)
#
# Copyright (c) 2020 ETH Zurich
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys
from .graph_tools import *
from satgen.isls import *
from satgen.ground_stations import *
from satgen.tles import *
import exputil
import cartopy
import cartopy.crs as ccrs
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


GROUND_STATION_USED_COLOR = "#3b3b3b"
GROUND_STATION_UNUSED_COLOR = "black"
SATELLITE_USED_COLOR = "#a61111"
SATELLITE_UNUSED_COLOR = "red"
ISL_COLOR = "#eb6b38"


def print_routes_and_rtt(base_output_dir, satellite_network_dir, dynamic_state_update_interval_ms,
                         simulation_end_time_s, src, dst):

    # Local shell
    local_shell = exputil.LocalShell()

    # Dynamic state dir can be inferred
    satellite_network_dynamic_state_dir = "%s/dynamic_state_%dms_for_%ds" % (
        satellite_network_dir, dynamic_state_update_interval_ms, simulation_end_time_s
    )

    # Default output dir assumes it is done manual
    pdf_dir = base_output_dir + "/pdf"
    data_dir = base_output_dir + "/data"
    local_shell.make_full_dir(pdf_dir)
    local_shell.make_full_dir(data_dir)

    # Variables (load in for each thread such that they don't interfere)
    ground_stations = read_ground_stations_extended(satellite_network_dir + "/ground_stations.txt")
    tles = read_tles(satellite_network_dir + "/tles.txt")
    list_isls = read_isls(satellite_network_dir + "/isls.txt")
    satellites = tles["satellites"]
    epoch = tles["epoch"]
    description = exputil.PropertiesConfig(satellite_network_dir + "/description.txt")

    # Derivatives
    simulation_end_time_ns = simulation_end_time_s * 1000 * 1000 * 1000
    dynamic_state_update_interval_ns = dynamic_state_update_interval_ms * 1000 * 1000
    max_gsl_length_m = exputil.parse_positive_float(description.get_property_or_fail("max_gsl_length_m"))
    max_isl_length_m = exputil.parse_positive_float(description.get_property_or_fail("max_isl_length_m"))

    # For each time moment
    fstate = {}
    current_path = []
    rtt_ns_list = []
    for t in range(0, simulation_end_time_ns, dynamic_state_update_interval_ns):
        with open(satellite_network_dynamic_state_dir + "/fstate_" + str(t) + ".txt", "r") as f_in:
            for line in f_in:
                spl = line.split(",")
                current = int(spl[0])
                destination = int(spl[1])
                next_hop = int(spl[2])
                fstate[(current, destination)] = next_hop

            # Calculate path length
            path_there = get_path(src, dst, fstate)
            path_back = get_path(dst, src, fstate)
            if path_there is not None and path_back is not None:
                length_src_to_dst_m = compute_path_length_without_graph(path_there, epoch, t, satellites,
                                                                        ground_stations, list_isls,
                                                                        max_gsl_length_m, max_isl_length_m)
                length_dst_to_src_m = compute_path_length_without_graph(path_back, epoch, t,
                                                                        satellites, ground_stations, list_isls,
                                                                        max_gsl_length_m, max_isl_length_m)
                rtt_ns = (length_src_to_dst_m + length_dst_to_src_m) * 1000000000.0 / 299792458.0
            else:
                length_src_to_dst_m = 0.0
                length_dst_to_src_m = 0.0
                rtt_ns = 0.0

            # Add to RTT list
            rtt_ns_list.append((t, rtt_ns))

            # Only if there is a new path, print new path
            new_path = get_path(src, dst, fstate)
            if current_path != new_path:

                # This is the new path
                current_path = new_path

                # Write change nicely to the console
                print("Change at t=" + str(t) + " ns (= " + str(t / 1e9) + " seconds)")
                print("  > Path..... " + (" -- ".join(list(map(lambda x: str(x), current_path)))
                                          if current_path is not None else "Unreachable"))
                print("  > Length... " + str(length_src_to_dst_m + length_dst_to_src_m) + " m")
                print("  > RTT...... %.2f ms" % (rtt_ns / 1e6))
                print("")

                # Now we make a pdf for it
                pdf_filename = pdf_dir + "/graphics_%d_to_%d_time_%dms.pdf" % (src, dst, int(t / 1000000))
                f = plt.figure()
                
                # Projection
                ax = plt.axes(projection=ccrs.PlateCarree())

                # Background
                ax.add_feature(cartopy.feature.OCEAN, zorder=0)
                ax.add_feature(cartopy.feature.LAND, zorder=0, edgecolor='black', linewidth=0.5)
                ax.add_feature(cartopy.feature.BORDERS, edgecolor='gray', linewidth=0.5)
                
                # Time moment
                time_moment_str = str(epoch + t * u.ns)

                # Other satellites
                for node_id in range(len(satellites)):
                    ephem_body = satellites[node_id]
                    ephem_body.compute(time_moment_str)
                    latitude_deg = math.degrees(ephem_body.sublat)
                    longitude_deg = math.degrees(ephem_body.sublong)

                    # Other satellite
                    plt.plot(
                        longitude_deg,
                        latitude_deg,
                        color=SATELLITE_UNUSED_COLOR,
                        fillstyle='none',
                        markeredgewidth=0.5,
                        marker='^',
                    )

                # # ISLs
                # for isl in list_isls:
                #     ephem_body = satellites[isl[0]]
                #     ephem_body.compute(time_moment_str)
                #     from_latitude_deg = math.degrees(ephem_body.sublat)
                #     from_longitude_deg = math.degrees(ephem_body.sublong)
                #
                #     ephem_body = satellites[isl[1]]
                #     ephem_body.compute(time_moment_str)
                #     to_latitude_deg = math.degrees(ephem_body.sublat)
                #     to_longitude_deg = math.degrees(ephem_body.sublong)
                #
                #     # Plot the line
                #     if ground_stations[src - len(satellites)]["longitude"] <= \
                #        from_longitude_deg \
                #        <= ground_stations[dst - len(satellites)]["longitude"] \
                #        and \
                #        ground_stations[src - len(satellites)]["latitude"] <= \
                #        from_latitude_deg \
                #        <= ground_stations[dst - len(satellites)]["latitude"] \
                #        and \
                #        ground_stations[src - len(satellites)]["longitude"] <= \
                #        to_longitude_deg \
                #        <= ground_stations[dst - len(satellites)]["longitude"] \
                #        and \
                #        ground_stations[src - len(satellites)]["latitude"] <= \
                #        to_latitude_deg \
                #        <= ground_stations[dst - len(satellites)]["latitude"]:
                #             plt.plot(
                #         [from_longitude_deg, to_longitude_deg],
                #         [from_latitude_deg, to_latitude_deg],
                #         color='#eb6b38', linewidth=0.1, marker='',
                #         transform=ccrs.Geodetic(),
                #     )

                # Other ground stations
                for gid in range(len(ground_stations)):
                    latitude_deg = ground_stations[gid]["latitude"]
                    longitude_deg = ground_stations[gid]["longitude"]

                    # Other ground station
                    plt.plot(
                        longitude_deg,
                        latitude_deg,
                        color=GROUND_STATION_UNUSED_COLOR,
                        fillstyle='none',
                        markeredgewidth=0.5,
                        marker='o',
                    )
                
                # Lines between
                for v in range(1, len(current_path)):
                    from_node_id = current_path[v - 1]
                    to_node_id = current_path[v]
                    
                    # From coordinates
                    if from_node_id < len(satellites):
                        ephem_body = satellites[from_node_id]
                        ephem_body.compute(time_moment_str)
                        from_latitude_deg = math.degrees(ephem_body.sublat)
                        from_longitude_deg = math.degrees(ephem_body.sublong)
                    else:
                        from_latitude_deg = ground_stations[from_node_id - len(satellites)]["latitude"]
                        from_longitude_deg = ground_stations[from_node_id - len(satellites)]["longitude"]

                    # To coordinates
                    if to_node_id < len(satellites):
                        ephem_body = satellites[to_node_id]
                        ephem_body.compute(time_moment_str)
                        to_latitude_deg = math.degrees(ephem_body.sublat)
                        to_longitude_deg = math.degrees(ephem_body.sublong)
                    else:
                        to_latitude_deg = ground_stations[to_node_id - len(satellites)]["latitude"]
                        to_longitude_deg = ground_stations[to_node_id - len(satellites)]["longitude"]

                    # Plot the line
                    plt.plot(
                        [from_longitude_deg, to_longitude_deg],
                        [from_latitude_deg, to_latitude_deg],
                        color=ISL_COLOR, linewidth=2, marker='',
                        transform=ccrs.Geodetic(),
                    )

                # Across all points, we need to find the latitude / longitude to zoom into
                min_latitude = min(
                    ground_stations[src - len(satellites)]["latitude"],
                    ground_stations[dst - len(satellites)]["latitude"]
                )
                max_latitude = max(
                    ground_stations[src - len(satellites)]["latitude"],
                    ground_stations[dst - len(satellites)]["latitude"]
                )
                min_longitude = min(
                    ground_stations[src - len(satellites)]["longitude"],
                    ground_stations[dst - len(satellites)]["longitude"]
                )
                max_longitude = max(
                    ground_stations[src - len(satellites)]["longitude"],
                    ground_stations[dst - len(satellites)]["longitude"]
                )

                # Points
                for v in range(0, len(current_path)):
                    node_id = current_path[v]
                    if node_id < len(satellites):
                        ephem_body = satellites[node_id]
                        ephem_body.compute(time_moment_str)
                        latitude_deg = math.degrees(ephem_body.sublat)
                        longitude_deg = math.degrees(ephem_body.sublong)
                        min_latitude = min(min_latitude, latitude_deg)
                        max_latitude = max(max_latitude, latitude_deg)
                        min_longitude = min(min_longitude, longitude_deg)
                        max_longitude = max(max_longitude, longitude_deg)
                        # Satellite
                        plt.plot(
                            longitude_deg,
                            latitude_deg,
                            color=SATELLITE_USED_COLOR,
                            marker='^',
                        )
                    else:
                        latitude_deg = ground_stations[node_id - len(satellites)]["latitude"]
                        longitude_deg = ground_stations[node_id - len(satellites)]["longitude"]
                        min_latitude = min(min_latitude, latitude_deg)
                        max_latitude = max(max_latitude, latitude_deg)
                        min_longitude = min(min_longitude, longitude_deg)
                        max_longitude = max(max_longitude, longitude_deg)
                        if v == 0 or v == len(current_path) - 1:
                            # Endpoint (start or finish) ground station
                            plt.plot(
                                longitude_deg,
                                latitude_deg,
                                color=GROUND_STATION_USED_COLOR,
                                marker='o',
                            )
                        else:
                            # Intermediary ground station
                            plt.plot(
                                longitude_deg,
                                latitude_deg,
                                color=GROUND_STATION_USED_COLOR,
                                marker='o',
                            )

                # Zoom into region
                ax.set_extent([
                    min_longitude - 5,
                    max_longitude + 5,
                    min_latitude - 5,
                    max_latitude + 5,
                ])

                # Legend
                ax.legend(
                    handles=(
                        Line2D([0], [0], marker='o', label="Ground station (used)",
                               linewidth=0, color='#3b3b3b', markersize=5),
                        Line2D([0], [0], marker='o', label="Ground station (unused)",
                               linewidth=0, color='black', markersize=5, fillstyle='none', markeredgewidth=0.5),
                        Line2D([0], [0], marker='^', label="Satellite (used)",
                               linewidth=0, color='#a61111', markersize=5),
                        Line2D([0], [0], marker='^', label="Satellite (unused)",
                               linewidth=0, color='red', markersize=5, fillstyle='none', markeredgewidth=0.5),
                    ),
                    loc='lower left',
                    fontsize='xx-small'
                )

                # Save final PDF figure
                f.savefig(pdf_filename, bbox_inches='tight')


def main():
    args = sys.argv[1:]
    if len(args) != 6:
        print("Must supply exactly six arguments")
        print("Usage: python print_graphical_routes_and_rtt.py [data_dir] [satellite_network_dir] "
              "[dynamic_state_update_interval_ms] [end_time_s] [src] [dst]")
        exit(1)
    else:
        core_network_folder_name = args[1].split("/")[-1]
        base_output_dir = "%s/%s/%dms_for_%ds/manual" % (
            args[0], core_network_folder_name, int(args[2]), int(args[3])
        )
        print("Data dir: " + args[0])
        print("Used data dir to form base output dir: " + base_output_dir)
        print_routes_and_rtt(
            base_output_dir,
            args[1],
            int(args[2]),
            int(args[3]),
            int(args[4]),
            int(args[5])
        )


if __name__ == "__main__":
    main()
