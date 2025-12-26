[3/6] Checking database status...

  Found 0 books and 0 verses in database.

  Database is empty. Building index (this may take 10-15 minutes)...

Traceback (most recent call last):

  File "<frozen runpy>", line 198, in _run_module_as_main

  File "<frozen runpy>", line 88, in _run_code

  File "/app/scripts/build_index.py", line 342, in <module>

    main()

  File "/app/scripts/build_index.py", line 328, in main

    asyncio.run(

  File "/usr/local/lib/python3.11/asyncio/runners.py", line 190, in run

    return runner.run(main)

           ^^^^^^^^^^^^^^^^

  File "/usr/local/lib/python3.11/asyncio/runners.py", line 118, in run

    return self._loop.run_until_complete(task)

           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

  File "/usr/local/lib/python3.11/asyncio/base_events.py", line 654, in run_until_complete

    return future.result()

           ^^^^^^^^^^^^^^^

  File "/app/scripts/build_index.py", line 245, in build_index

    await import_from_json(session, json_path, verbose)

  File "/app/scripts/build_index.py", line 68, in import_from_json

    raise ValueError(

ValueError: Database already contains 66 books. Use --drop-existing flag to clear existing data first, or the data import will fail due to unique constraint violations.

Database initialized with extensions and tables