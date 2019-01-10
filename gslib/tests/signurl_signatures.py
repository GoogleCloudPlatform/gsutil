TEST_SIGN_PUT_SIG_PY2 = ('https://storage.googleapis.com/test/test.txt?x-goog-signature='
                         '8c4d7226d8db1c939381d421c422c8724a762250d7ab9f79eaf943f8c0d05e'
                         '8eac43ef94cec44d8ab3f15d0f0243ad07bb1de470cc31099bdcbdf5555e1c'
                         '41d060fca84ea64681d7a926b5e2faafac97cf1bbb1d66f0167fc7144566a2'
                         '5fe2f5a708961046d6b195ba08a04b501d8b014f4fa203a5ac3d6c5effc5ea'
                         '549a68c9f353b050d5ea23786845307512bc051424151d2f515391ade2304d'
                         'db5bb44146ac83b89850b77ffeedbdd0682c9a1d1ae2e8dd75ad43c8263e35'
                         '8592c84f879fdb8b733feec0b516963bd17990d0e89a306744ca1de6d6fbaa'
                         '16ca9e82aacd1f64f2d43ae261ada2104ff481a1754b6f357d2c54fc2d127f'
                         '0b0bbe0f300776d0&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-cred'
                         'ential=test%40developer.gserviceaccount.com%2F19000101%2Fus-ea'
                         'st%2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-go'
                         'og-expires=3600&x-goog-signedheaders=host%3Bx-goog-resumable')

TEST_SIGN_PUT_SIG_PY3 = "https://storage.googleapis.com/test/test.txt?x-goog-signature=b'2a045db18685eae0817a536d2406f544447959fa9bfac6461bdca2ae3e8e05e46f4516c6c89ecb7e9874ef02718432d2e7c852ef9a5d928f93dc76d96f9104287c053f4074d55d0be58478b658cff7ff256f02f9b97ed407f6a2d2a1b55adfb67ddbf81379922fdcaa5a3bfcee0a227bf5d40155ad4ff668940746a38683e09f268ad5f02e75da1a1ba02421ff17bcfc20089bbff05ef10da5281bbcffc096686bfeaad8639326e44ca78c369b00544286e303e3f91f3141c4b3b58f87dfcdde7e0bb62c3a69ba807758e1ddbb996b2435fd3776276cd0e18b7b29e2f6b2695b751131d76e021eb9f80a125e2a3ba7c77edc9b7aea655f76122bb75ae10499db'&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-credential=test%40developer.gserviceaccount.com%2F19000101%2Fus-east%2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-expires=3600&x-goog-signedheaders=host%3Bx-goog-resumable"

TEST_SIGN_RESUMABLE_PY2 = ('https://storage.googleapis.com/test/test.txt?x-goog-signature='
                           '8c4d7226d8db1c939381d421c422c8724a762250d7ab9f79eaf943f8c0d05e'
                           '8eac43ef94cec44d8ab3f15d0f0243ad07bb1de470cc31099bdcbdf5555e1c'
                           '41d060fca84ea64681d7a926b5e2faafac97cf1bbb1d66f0167fc7144566a2'
                           '5fe2f5a708961046d6b195ba08a04b501d8b014f4fa203a5ac3d6c5effc5ea'
                           '549a68c9f353b050d5ea23786845307512bc051424151d2f515391ade2304d'
                           'db5bb44146ac83b89850b77ffeedbdd0682c9a1d1ae2e8dd75ad43c8263e35'
                           '8592c84f879fdb8b733feec0b516963bd17990d0e89a306744ca1de6d6fbaa'
                           '16ca9e82aacd1f64f2d43ae261ada2104ff481a1754b6f357d2c54fc2d127f'
                           '0b0bbe0f300776d0&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-cred'
                           'ential=test%40developer.gserviceaccount.com%2F19000101%2Fus-ea'
                           'st%2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-go'
                           'og-expires=3600&x-goog-signedheaders=host%3Bx-goog-resumable')

TEST_SIGN_RESUMABLE_PY3 = "https://storage.googleapis.com/test/test.txt?x-goog-signature=b'2a045db18685eae0817a536d2406f544447959fa9bfac6461bdca2ae3e8e05e46f4516c6c89ecb7e9874ef02718432d2e7c852ef9a5d928f93dc76d96f9104287c053f4074d55d0be58478b658cff7ff256f02f9b97ed407f6a2d2a1b55adfb67ddbf81379922fdcaa5a3bfcee0a227bf5d40155ad4ff668940746a38683e09f268ad5f02e75da1a1ba02421ff17bcfc20089bbff05ef10da5281bbcffc096686bfeaad8639326e44ca78c369b00544286e303e3f91f3141c4b3b58f87dfcdde7e0bb62c3a69ba807758e1ddbb996b2435fd3776276cd0e18b7b29e2f6b2695b751131d76e021eb9f80a125e2a3ba7c77edc9b7aea655f76122bb75ae10499db'&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-credential=test%40developer.gserviceaccount.com%2F19000101%2Fus-east%2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-expires=3600&x-goog-signedheaders=host%3Bx-goog-resumable"

TEST_SIGN_URL_PUT_CONTENT_PY2 = ('https://storage.googleapis.com/test/test.txt?x-goog-signature='
                                 '590b52cb0be515032578f372029a72dd7fc253ceb1b50b8cd5761af835b119'
                                 '2d461adbb16b6d292e48a5b17f9d4078327a7f1ceed7fa3e15155c1d251398'
                                 'a445b6346075a22bf7a6250264c983503e819eada2a3895213439ce3c9f590'
                                 '564e54cbca436e1bcd677c36ec33224c1a074c376953fcd7514a6a7ea93cde'
                                 '2dd698e9b461a697c9e4e30539cd5c3bd88172797c867955b388bc28e60d6b'
                                 'b8a7fb302d2eb988ef5056843c2105f177c44fc98c202ece26bf288c02ded4'
                                 'e7cdb85cb29584879e9765027a8ce99a4fedfda995d5e035114c5f8a8bfa94'
                                 '8c438b2714e4a128dc46986336573139d4009f3a75fdbbb757603cff491c0b'
                                 '014698ce171c9fe9&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-cred'
                                 'ential=test%40developer.gserviceaccount.com%2F19000101%2Feu%2F'
                                 'storage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-ex'
                                 'pires=3600&x-goog-signedheaders=content-type%3Bhost')

TEST_SIGN_URL_PUT_CONTENT_PY3 = "https://storage.googleapis.com/test/test.txt?x-goog-signature=b'29e990388a09e9165e2bf205d637843dc3d305d7731bf75a6d406ad883adedd6e40e473625274e31ee6188edf4938a96758aef2bf0df08df6447d77be12e815619bc2aa86ecfda9315d2eb03b6f0512a1235e8a0fc8411841039b94ccc3e65ac85ba6689eab1569478c3a5d080e0056ab6cf69e6e4c093058c1530a50e9ada9d5e38c27224137b0833215c7be8c0525e693daabf098dd9837e9ce3cfd3dbe815468f6b4ec57a4de3a8164cefbad6f9d700b123499b76604ff6d1ec81618bea500cbefe9e117b4c3126f5d31b4242bd5db2ff51e4cff21076f55f6cd34f761d42cfdb2770546f3878408813ce9adc777bd0446f6a0ed97dcfc39bd986f360223c'&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-credential=test%40developer.gserviceaccount.com%2F19000101%2Feu%2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-expires=3600&x-goog-signedheaders=content-type%3Bhost"

TEST_SIGN_URL_GET_PY2 = ('https://storage.googleapis.com/test/test.txt?x-goog-signature='
                         '2ed227f18d31cdf2b01da7cd4fcea45330fbfcc0dda1d327a8c27124a276ee'
                         'e0de835e9cd4b0bee609d6b4b21a88a8092a9c089574a300243dde38351f0d'
                         '183df007211ded41f2f0854290b995be6c9d0367d9c00976745ba27740238b'
                         '0dd49fee7c41e7ed1569bbab8ffbb00a2078e904ebeeec2f8e55e93d4baba1'
                         '3db5dc670b1b16183a15d5067f1584db88b3dc55e3edd3c97c0f31fec99ea4'
                         'ce96ddb8235b0352c9ce5110dad1a580072d955fe9203b6701364ddd85226b'
                         '55bec84ac46e48cd324fd5d8d8ad264d1aa0b7dbad3ac04b87b2a6c2c8ef95'
                         '3285cbe3b431e5def84552e112899459fcb64d2d84320c06faa1e8efa26eca'
                         'cce2eff41f2d2364&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-cred'
                         'ential=test%40developer.gserviceaccount.com%2F19000101%2Fasia%'
                         '2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-'
                         'expires=0&x-goog-signedheaders=host')

TEST_SIGN_URL_GET_PY3 = "https://storage.googleapis.com/test/test.txt?x-goog-signature=b'5d2c2179fe191b95f52a8df108c5d71ade3c758cdc56cac4409012629bfbc9f0343a473bd8fc98cb05b6510e2e05a89c3a410dd2b6dc0ca48546221bec9b0a4d73a16c45eb3e2ea115482caf5547ca24c1e388d33a59be583b730f268998a47b9b284b25a66d611564f8b56c7cad1eea4049e8838d8d8cfc85c1d2d073f513118446b59bfd7f20bc59786e1034a8d7c4d565fb2deeb89ffea1eaa535f9cb87e78eb87c479cdda95f23551b8b7c6974b82105210806d7285c5361c4203192dbf12de7ac376681ee72cc460ab6828eef3b8ca2e6ac5590f925f7497bc3fb15d3e4a1d8084c6b02b09e1be96070c776511669bfa47a6e250b429e2298c05470a9d5'&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-credential=test%40developer.gserviceaccount.com%2F19000101%2Fasia%2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-expires=0&x-goog-signedheaders=host"

TEST_SIGN_URL_GET_WITH_JSON_KEY_PY2 = ('https://storage.googleapis.com/test/test.txt?x-goog-signature='
                                       '2ed227f18d31cdf2b01da7cd4fcea45330fbfcc0dda1d327a8c27124a276ee'
                                       'e0de835e9cd4b0bee609d6b4b21a88a8092a9c089574a300243dde38351f0d'
                                       '183df007211ded41f2f0854290b995be6c9d0367d9c00976745ba27740238b'
                                       '0dd49fee7c41e7ed1569bbab8ffbb00a2078e904ebeeec2f8e55e93d4baba1'
                                       '3db5dc670b1b16183a15d5067f1584db88b3dc55e3edd3c97c0f31fec99ea4'
                                       'ce96ddb8235b0352c9ce5110dad1a580072d955fe9203b6701364ddd85226b'
                                       '55bec84ac46e48cd324fd5d8d8ad264d1aa0b7dbad3ac04b87b2a6c2c8ef95'
                                       '3285cbe3b431e5def84552e112899459fcb64d2d84320c06faa1e8efa26eca'
                                       'cce2eff41f2d2364&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-cred'
                                       'ential=test%40developer.gserviceaccount.com%2F19000101%2Fasia%'
                                       '2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-'
                                       'expires=0&x-goog-signedheaders=host')

TEST_SIGN_URL_GET_WITH_JSON_KEY_PY3 = "https://storage.googleapis.com/test/test.txt?x-goog-signature=b'5d2c2179fe191b95f52a8df108c5d71ade3c758cdc56cac4409012629bfbc9f0343a473bd8fc98cb05b6510e2e05a89c3a410dd2b6dc0ca48546221bec9b0a4d73a16c45eb3e2ea115482caf5547ca24c1e388d33a59be583b730f268998a47b9b284b25a66d611564f8b56c7cad1eea4049e8838d8d8cfc85c1d2d073f513118446b59bfd7f20bc59786e1034a8d7c4d565fb2deeb89ffea1eaa535f9cb87e78eb87c479cdda95f23551b8b7c6974b82105210806d7285c5361c4203192dbf12de7ac376681ee72cc460ab6828eef3b8ca2e6ac5590f925f7497bc3fb15d3e4a1d8084c6b02b09e1be96070c776511669bfa47a6e250b429e2298c05470a9d5'&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-credential=test%40developer.gserviceaccount.com%2F19000101%2Fasia%2Fstorage%2Fgoog4_request&x-goog-date=19000101T000555Z&x-goog-expires=0&x-goog-signedheaders=host"
