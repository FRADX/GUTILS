from glider_utils.yo import create_profile_entry


def filter_profiles(profiles, dataset, conditional):
    """Filters out profiles that do not meet some criteria

    Returns the filtered set of profiles
    """

    filtered_profiles = []
    start_index = 0
    for profile in profiles:
        end_index = profile['index_bounds'][1]
        if conditional(profile):
            filtered_profiles.append(
                create_profile_entry(
                    dataset,
                    start_index,
                    end_index
                )
            )
            start_index = end_index + 1
        elif len(dataset)-1 == end_index:
            filtered_profiles.append(
                create_profile_entry(
                    dataset,
                    start_index,
                    end_index
                )
            )

    return filtered_profiles

# Convenience methods follow


def filter_profile_depth(profiles, dataset, below=1):
    """Filters out profiles that are not below a certain depth (Default: 1m)

    Returns the filtered set of profiles
    """

    def conditional(profile):
        depth_max = max(profile['depth_bounds'])
        return depth_max >= below

    return filter_profiles(profiles, dataset, conditional)


def filter_profile_time(profiles, dataset, timespan_condition):
    """Filters out profiles that do not span a specified number of seconds

    Returns the filtered set of profiles
    """

    def conditional(profile):
        timespan = profile['time_bounds'][1] - profile['time_bounds'][0]
        return timespan >= timespan_condition

    return filter_profiles(profiles, dataset, conditional)


def filter_profile_distance(profiles, dataset, distance_condition):
    """Filters out profiles that do not span a specified vertical distance

    Returns the filtered set of profiles
    """

    def conditional(profile):
        distance = abs(profile['depth_bounds'][1] - profile['depth_bounds'][0])
        return distance >= distance_condition

    return filter_profiles(profiles, dataset, conditional)


def filter_profile_number_of_points(profiles, dataset, points_condition):
    """Filters out profiles that do not have a specified number of points

    Returns the filtered set of profiles
    """

    def conditional(profile):
        num_points = profile['index_bounds'][1] - profile['index_bounds'][0]
        return num_points >= points_condition

    return filter_profiles(profiles, dataset, conditional)
