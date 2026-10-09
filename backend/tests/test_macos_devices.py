from smart_meeting.audio.macos import real_microphone


def device(index, name):
    return {"index": index, "name": name, "max_input_channels": 1}


TEAMS = device(0, "Microsoft Teams Audio")
MACBOOK = device(1, "Microphone (MacBook Pro)")
HEADSET = device(2, "Jabra Evolve2 65")


def test_the_default_microphone_is_kept_when_it_is_a_real_one():
    assert real_microphone([TEAMS, MACBOOK, HEADSET], 2) == HEADSET


def test_a_virtual_default_input_gives_way_to_the_built_in_microphone():
    # The call itself as microphone: everything the others say came twice
    assert real_microphone([TEAMS, HEADSET, MACBOOK], 0) == MACBOOK


def test_without_built_in_microphone_the_first_real_input():
    assert real_microphone([TEAMS, HEADSET, device(3, "BlackHole 2ch")], 0) == HEADSET
