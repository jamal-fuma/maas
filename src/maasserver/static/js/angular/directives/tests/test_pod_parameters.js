/* Copyright 2017 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Unit tests for pod parameters directive.
 */

describe("maasPodParameters", function() {

    // Load the MAAS module.
    beforeEach(module("MAAS"));

    // Get managers before the test.
    var PodsManager, GeneralManager, ManagerHelperService;
    beforeEach(inject(function($injector) {
        PodsManager = $injector.get("PodsManager");
        GeneralManager = $injector.get("GeneralManager");
        ManagerHelperService = $injector.get("ManagerHelperService");
    }));

    // Create a new scope before each test.
    var $scope;
    beforeEach(inject(function($rootScope) {
        $scope = $rootScope.$new();
        $scope.obj = {};
    }));

    // Return the compiled directive.
    function compileDirective() {
        var directive;
        var html = [
            '<div>',
              '<maas-obj-form obj="obj" manager="manager" ',
                'table-form="true" save-on-blur="false">',
                '<maas-pod-parameters></maas-pod-parameters>',
              '</maas-obj-form>',
            "</div>"
        ].join('');

        // Compile the directive.
        inject(function($compile) {
            directive = $compile(html)($scope);
        });

        // Perform the digest cycle to finish the compile.
        $scope.$digest();
        return angular.element(directive.find("maas-pod-parameters"));
    }

    it("add type field to maasForm", function() {
        var directive = compileDirective();
        expect($scope.obj.$maasForm.fields.type).toBeDefined();
    });

    describe("with powerTypes", function() {

        var podTypes, powerTypes, directive;
        beforeEach(function() {
            powerTypes = [
                {
                    name: 'virsh',
                    description: 'Virsh',
                    driver_type: 'pod',
                    fields: [
                        {
                            name: 'power_address',
                            label: 'Pod address',
                            scope: 'bmc'
                        },
                        {
                            name: 'power_id',
                            label: 'Power ID',
                            scope: 'node'
                        }
                    ]
                },
                {
                    name: 'rsd',
                    description: 'RSD',
                    driver_type: 'pod',
                    fields: [
                        {
                            name: 'rsd_address',
                            label: 'Pod address',
                            scope: 'bmc'
                        },
                        {
                            name: 'rsd_id',
                            label: 'Power ID',
                            scope: 'node'
                        }
                    ]
                },
                {
                    name: 'ipmi',
                    description: 'IPMI',
                    driver_type: 'power',
                    fields: []
                }
            ];
            podTypes = [powerTypes[0], powerTypes[1]];

            GeneralManager._data.power_types.data = powerTypes;
            directive = compileDirective();
        });

        it("sets podTypes", function() {
          var scope = directive.scope();
          expect(scope.podTypes).toEqual(podTypes);
        });

        it("renders fields when type set", function() {
          $scope.obj.$maasForm.updateValue('type', 'virsh');
          $scope.$digest();

          expect($scope.obj.$maasForm.fields.power_address).toBeDefined();
          expect($scope.obj.$maasForm.fields.power_id).toBeUndefined();
        });

        it("switches fields when type changed", function() {
          $scope.obj.$maasForm.updateValue('type', 'virsh');
          $scope.$digest();
          $scope.obj.$maasForm.updateValue('type', 'rsd');
          $scope.$digest();

          expect($scope.obj.$maasForm.fields.power_address).toBeUndefined();
          expect($scope.obj.$maasForm.fields.power_id).toBeUndefined();
          expect($scope.obj.$maasForm.fields.rsd_address).toBeDefined();
          expect($scope.obj.$maasForm.fields.rsd_id).toBeUndefined();
        });
    });
});
