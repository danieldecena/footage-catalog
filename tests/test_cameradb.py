import sqlite3
import pytest
from footcat import cameradb


@pytest.fixture
def fake_card(tmp_path):
    misc = tmp_path / "MISC"; misc.mkdir()
    c = sqlite3.connect(misc / "AC006.db")
    c.executescript("""
      create table gis_info_table(ID integer, dcf_index integer, camera_type integer,
        file_name text, uuid integer, file_type integer, sub_type integer,
        result integer, star integer, origin integer, cloud_download integer,
        highlight integer, video_index integer, image_index integer);
      create table video_info_table(ID integer, duration integer, frame_num integer,
        frame_den integer, rotation integer, resolution_width integer,
        resolution_height integer, gps_status integer, steady_mode integer,
        fov_type integer, bit_depth integer, model_name text);
      create table mtime_table(dcf_index integer, mtime integer);
    """)
    c.execute("insert into gis_info_table values"
              "(1,1048640,0,'/mnt/DCIM/DJI_001/DJI_20260915000324_0001_D.MP4',"
              "893099253,64,0,1,0,0,0,1,79,0)")
    c.execute("insert into gis_info_table values"
              "(2,1048640,0,'/mnt/DCIM/DJI_001/DJI_20260915000324_0001_D.LRF',"
              "893099253,64,0,1,0,0,0,0,80,0)")
    c.execute("insert into video_info_table values"
              "(79,71171,30000,1001,90,1920,1080,0,2,1,10,'DJI AC006')")
    c.execute("insert into video_info_table values"
              "(80,71171,30000,1001,0,1280,720,0,2,1,8,'DJI AC006')")
    c.execute("insert into mtime_table values(1048640,1789430678)")
    c.commit(); c.close()
    return tmp_path


def test_find_camera_db(fake_card):
    assert cameradb.find_camera_db(fake_card).name == "AC006.db"


def test_find_returns_none_when_absent(tmp_path):
    assert cameradb.find_camera_db(tmp_path) is None


def test_read_keys_by_basename(fake_card):
    recs = cameradb.read(cameradb.find_camera_db(fake_card))
    assert "DJI_20260915000324_0001_D.MP4" in recs
    assert "DJI_20260915000324_0001_D.LRF" in recs


def test_read_extracts_flags_and_rotation(fake_card):
    r = cameradb.read(cameradb.find_camera_db(fake_card))["DJI_20260915000324_0001_D.MP4"]
    assert r.highlight == 1 and r.star == 0
    assert r.rotation == 90
    assert r.width == 1920 and r.height == 1080
    assert r.duration_ms == 71171
    assert r.gps_status == 0
    assert r.model_name == "DJI AC006"


def test_proxy_row_is_distinct_from_primary(fake_card):
    recs = cameradb.read(cameradb.find_camera_db(fake_card))
    assert recs["DJI_20260915000324_0001_D.LRF"].width == 1280
    assert recs["DJI_20260915000324_0001_D.LRF"].highlight == 0


def test_read_joins_epoch_from_mtime_table(fake_card):
    r = cameradb.read(cameradb.find_camera_db(fake_card))["DJI_20260915000324_0001_D.MP4"]
    assert r.epoch == 1789430678


def test_corrupt_db_returns_empty(tmp_path):
    p = tmp_path / "bad.db"; p.write_bytes(b"not a database")
    assert cameradb.read(p) == {}


def test_missing_tables_return_empty(tmp_path):
    p = tmp_path / "empty.db"
    sqlite3.connect(p).close()
    assert cameradb.read(p) == {}


def test_audio_source_is_read(tmp_path):
    import sqlite3
    misc = tmp_path / "MISC"; misc.mkdir()
    c = sqlite3.connect(misc / "AC006.db")
    c.executescript("""
      create table gis_info_table(ID integer, dcf_index integer, file_name text,
        star integer, highlight integer, video_index integer);
      create table video_info_table(ID integer, duration integer, frame_num integer,
        frame_den integer, rotation integer, resolution_width integer,
        resolution_height integer, gps_status integer, steady_mode integer,
        fov_type integer, bit_depth integer, model_name text, app_audio_status integer);
      create table mtime_table(dcf_index integer, mtime integer);
    """)
    c.execute("insert into gis_info_table values(1,1,'/x/DJI_20260917120001_0001_D.MP4',0,0,9)")
    c.execute("insert into video_info_table values(9,1000,30000,1001,0,1920,1080,0,2,1,10,'DJI AC006',1)")
    c.commit(); c.close()
    from footcat import cameradb
    rec = cameradb.read(cameradb.find_camera_db(tmp_path))["DJI_20260917120001_0001_D.MP4"]
    assert rec.app_audio == 1


def test_reader_tolerates_a_database_missing_optional_columns(tmp_path):
    """Older firmware has no app_audio_status — that must cost us that field,
    not the entire read."""
    import sqlite3
    misc = tmp_path / "MISC"; misc.mkdir()
    c = sqlite3.connect(misc / "AC006.db")
    c.executescript("""
      create table gis_info_table(ID integer, dcf_index integer, file_name text,
        star integer, highlight integer, video_index integer);
      create table video_info_table(ID integer, duration integer, rotation integer);
      create table mtime_table(dcf_index integer, mtime integer);
    """)
    c.execute("insert into gis_info_table values(1,7,'/x/DJI_20260917120001_0001_D.MP4',0,1,9)")
    c.execute("insert into video_info_table values(9,4200,90)")
    c.execute("insert into mtime_table values(7,1789430678)")
    c.commit(); c.close()
    from footcat import cameradb
    recs = cameradb.read(cameradb.find_camera_db(tmp_path))
    r = recs["DJI_20260917120001_0001_D.MP4"]
    assert r.highlight == 1 and r.duration_ms == 4200 and r.rotation == 90
    assert r.epoch == 1789430678
    assert r.app_audio is None and r.fov_type is None
