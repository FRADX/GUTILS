import numpy.ma as ma
import numpy as np
import pandas as pd

NOT_ASSIGN = -1
GO_UP = 0
GO_DOWN = 1
CURVE_UP = 2
CURVE_DOWN = 3
CURVE = 4
STRAIGHT = 5


def is_masked(num):
    return np.isnan(num)


def look_ahead(start_point, num_look_ahead, depth_list):
    """
    Every time look ahead function is called, it will  go though next "num_look_ahead" number of points,
    and return the result about it there a curve coming and what is the direction of the points(go up or go down).
    :param start_point: which point to look ahead
    :param num_look_ahead: how many point this function will look ahead
    :param depth_list:
    :return:
    """
    length_of_depth_list = start_point + num_look_ahead
    # make sure not exceed max length
    if length_of_depth_list > len(depth_list):
        length_of_depth_list = len(depth_list)
    # the change of the direction
    change_direction = 0
    previous_depth = NOT_ASSIGN
    first_depth = NOT_ASSIGN
    direction = NOT_ASSIGN
    for index in range(start_point, length_of_depth_list):
        # set up first depth
        if previous_depth == NOT_ASSIGN:
            current_depth = depth_list[index]
            first_depth = current_depth
            if not is_masked(current_depth):
                previous_depth = depth_list[index]
        else:
            current_depth = depth_list[index]
            if not is_masked(current_depth):
                # set up the direction of the path
                if direction == NOT_ASSIGN:
                    if previous_depth >= current_depth:
                        direction = GO_UP
                        first_depth = first_depth - current_depth
                    else:
                        direction = GO_DOWN
                        first_depth = first_depth + current_depth
                else:
                    if previous_depth >= current_depth and direction == GO_UP:
                        change_direction = change_direction + 1
                        direction = GO_UP
                        first_depth = first_depth - current_depth
                    elif previous_depth <= current_depth and direction == GO_DOWN:
                        change_direction = change_direction + 1
                        direction = GO_DOWN
                        first_depth = first_depth + current_depth
                previous_depth = current_depth
    # not curve show up
    if change_direction == 0:
        return STRAIGHT
    # 1 curve
    elif change_direction == 1:
        if first_depth >= 0:
            return CURVE_DOWN
        else:
            return CURVE_UP
    # multi curve
    elif change_direction > 1:
        if first_depth >= 0:
            return GO_DOWN
        else:
            return GO_UP


def adjust_profile_id(depth, profile_id, num_look_ahead):
    direction = NOT_ASSIGN
    last_depth = NOT_ASSIGN
    previous_profile_id = NOT_ASSIGN
    profile_id = profile_id.copy()
    length = len(depth)
    curve_flag = False
    look_ahead_lock = NOT_ASSIGN
    for index in range(0, length):
        current_depth = depth[index]
        current_profile_id = profile_id[index]
        if not (is_masked(current_depth) or is_masked(current_profile_id)):
            if last_depth == NOT_ASSIGN or previous_profile_id == NOT_ASSIGN:
                # set up fist id.
                last_depth = current_depth
                previous_profile_id = current_profile_id
            else:
                if direction == NOT_ASSIGN:
                    if current_depth > last_depth:
                        direction = GO_DOWN
                    else:
                        direction = GO_UP
                else:
                    if previous_profile_id != current_profile_id:
                        # if profile id change
                        if (current_depth > last_depth and direction == GO_DOWN) or (
                                        current_depth < last_depth and direction == GO_UP):
                            # gilder go deeper or go upper
                            if not curve_flag:
                                # not sure is there a curve ahead, then look ahead
                                look_ahead_flag = look_ahead(index, num_look_ahead, depth)
                                if look_ahead_flag == CURVE_UP or look_ahead_flag == CURVE_DOWN:
                                    # if there is a curve ahead, then set flag curve as true
                                    curve_flag = True
                            # change the profile id
                            current_profile_id = previous_profile_id
                            profile_id[index] = current_profile_id
                    else:
                        if (current_depth > last_depth and direction == GO_DOWN) or (
                                        current_depth < last_depth and direction == GO_UP):
                            pid = previous_profile_id
                            profile_id[index] = pid
                        else:
                            if curve_flag:
                                # extreme point and change direction
                                if current_depth > last_depth:
                                    direction = GO_DOWN
                                else:
                                    direction = GO_UP
                                curve_flag = False
                            else:
                                if look_ahead_lock == NOT_ASSIGN:
                                    look_ahead_flag = look_ahead(index, num_look_ahead, depth)
                                    look_ahead_lock = index + num_look_ahead
                                    if look_ahead_flag == GO_UP:
                                        direction = GO_UP
                                    else:
                                        direction = GO_DOWN
                                elif look_ahead_lock <= index:
                                    look_ahead_flag = look_ahead(index, num_look_ahead, depth)
                                    look_ahead_lock = index + num_look_ahead
                                    if look_ahead_flag == GO_UP:
                                        direction = GO_UP
                                    else:
                                        direction = GO_DOWN
            last_depth = current_depth
            previous_profile_id = current_profile_id
        elif ((is_masked(current_depth) and is_masked(current_profile_id) == False)):
            current_profile_id = previous_profile_id
            profile_id[index] = current_profile_id
            previous_profile_id = current_profile_id
    return profile_id


def reassign_profile_id(df):
    if df is None:
        return df

    depth = df['z']
    profile_id = df['profile']
    #print(len(profile_id.unique()))
    new_profile_id = adjust_profile_id(depth, profile_id, 50)
    #print(len(new_profile_id.unique()))
    df['profile'] = new_profile_id
    return df
