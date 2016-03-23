/* Copyright 2015 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Unit tests for DomainsListController.
 */

describe("DomainDetailsController", function() {

    // Load the MAAS module.
    beforeEach(module("MAAS"));

    // Make a fake domain
    function makeDomain() {
        var domain = {
            id: makeInteger(1, 10000),
            name: 'example.com',
            authoritative: true
        };
        DomainsManager._items.push(domain);
        return domain;
    }

    // Grab the needed angular pieces.
    var $controller, $rootScope, $location, $scope, $q, $routeParams;
    beforeEach(inject(function($injector) {
        $controller = $injector.get("$controller");
        $rootScope = $injector.get("$rootScope");
        $location = $injector.get("$location");
        $scope = $rootScope.$new();
        $q = $injector.get("$q");
        $routeParams = {};
    }));

    // Load any injected managers and services.
    var DomainsManager, UsersManager, ManagerHelperService, ErrorService;
    beforeEach(inject(function($injector) {
        DomainsManager = $injector.get("DomainsManager");
        UsersManager = $injector.get("UsersManager");
        ManagerHelperService = $injector.get("ManagerHelperService");
        ErrorService = $injector.get("ErrorService");
    }));

    var domain;
    beforeEach(function() {
        domain = makeDomain();
    });

    // Makes the NodesListController
    function makeController(loadManagerDefer) {
        spyOn(UsersManager, "isSuperUser").and.returnValue(true);
        var loadManagers = spyOn(ManagerHelperService, "loadManagers");
        if(angular.isObject(loadManagerDefer)) {
            loadManagers.and.returnValue(loadManagerDefer.promise);
        } else {
            loadManagers.and.returnValue($q.defer().promise);
        }

        // Create the controller.
        var controller = $controller("DomainDetailsController", {
            $scope: $scope,
            $rootScope: $rootScope,
            $routeParams: $routeParams,
            $location: $location,
            DomainsManager: DomainsManager,
            UsersManager: UsersManager,
            ManagerHelperService: ManagerHelperService,
            ErrorService: ErrorService
        });

        return controller;
    }

    // Make the controller and resolve the setActiveItem call.
    function makeControllerResolveSetActiveItem() {
        var setActiveDefer = $q.defer();
        spyOn(DomainsManager, "setActiveItem").and.returnValue(
            setActiveDefer.promise);
        var defer = $q.defer();
        var controller = makeController(defer);
        $routeParams.domain_id = domain.id;

        defer.resolve();
        $rootScope.$digest();
        setActiveDefer.resolve(domain);
        $rootScope.$digest();

        return controller;
    }

    it("sets title and page on $rootScope", function() {
        var controller = makeController();
        expect($rootScope.title).toBe("Loading...");
        expect($rootScope.page).toBe("domains");
    });

    it("calls loadManagers with [DomainsManager, UsersManager]" +
        function() {
            var controller = makeController();
            expect(ManagerHelperService.loadManagers).toHaveBeenCalledWith(
                [DomainsManager, UsersManager]);
    });

    it("raises error if domain identifier is invalid", function() {
        spyOn(DomainsManager, "setActiveItem").and.returnValue(
            $q.defer().promise);
        spyOn(ErrorService, "raiseError").and.returnValue(
            $q.defer().promise);
        var defer = $q.defer();
        var controller = makeController(defer);
        $routeParams.domain_id = 'xyzzy';

        defer.resolve();
        $rootScope.$digest();

        expect($scope.domain).toBe(null);
        expect($scope.loaded).toBe(false);
        expect(DomainsManager.setActiveItem).not.toHaveBeenCalled();
        expect(ErrorService.raiseError).toHaveBeenCalled();
    });

    it("doesn't call setActiveItem if domain is loaded", function() {
        spyOn(DomainsManager, "setActiveItem").and.returnValue(
            $q.defer().promise);
        var defer = $q.defer();
        var controller = makeController(defer);
        DomainsManager._activeItem = domain;
        $routeParams.domain_id = domain.id;

        defer.resolve();
        $rootScope.$digest();

        expect($scope.domain).toBe(domain);
        expect($scope.loaded).toBe(true);
        expect(DomainsManager.setActiveItem).not.toHaveBeenCalled();
    });

    it("calls setActiveItem if domain is not active", function() {
        spyOn(DomainsManager, "setActiveItem").and.returnValue(
            $q.defer().promise);
        var defer = $q.defer();
        var controller = makeController(defer);
        $routeParams.domain_id = domain.id;

        defer.resolve();
        $rootScope.$digest();

        expect(DomainsManager.setActiveItem).toHaveBeenCalledWith(
            domain.id);
    });

    it("sets domain and loaded once setActiveItem resolves", function() {
        var controller = makeControllerResolveSetActiveItem();
        expect($scope.domain).toBe(domain);
        expect($scope.loaded).toBe(true);
    });

    it("title is updated once setActiveItem resolves", function() {
        var controller = makeControllerResolveSetActiveItem();
        expect($rootScope.title).toBe(domain.name);
    });

    it("default domain title is special", function() {
        domain.id = 0;
        var controller = makeControllerResolveSetActiveItem();
        expect($rootScope.title).toBe("Default domain " + domain.name);
    });

    describe("canBeDeleted", function() {

        it("returns false if domain is null", function() {
            var controller = makeControllerResolveSetActiveItem();
            $scope.domain = null;
            expect($scope.canBeDeleted()).toBe(false);
        });

        it("returns false if domain has resources", function() {
            var controller = makeControllerResolveSetActiveItem();
            $scope.domain.rrsets = [makeInteger()];
            expect($scope.canBeDeleted()).toBe(false);
        });

        it("returns true if domain has no resources", function() {
            var controller = makeControllerResolveSetActiveItem();
            $scope.domain.rrsets = [];
            expect($scope.canBeDeleted()).toBe(true);
        });
    });

    describe("deleteButton", function() {

        it("confirms delete", function() {
            var controller = makeControllerResolveSetActiveItem();
            $scope.deleteButton();
            expect($scope.confirmingDelete).toBe(true);
        });

        it("clears error", function() {
            var controller = makeControllerResolveSetActiveItem();
            $scope.error = makeName("error");
            $scope.deleteButton();
            expect($scope.error).toBeNull();
        });
    });

    describe("cancelDeleteButton", function() {

        it("cancels delete", function() {
            var controller = makeControllerResolveSetActiveItem();
            $scope.deleteButton();
            $scope.cancelDeleteButton();
            expect($scope.confirmingDelete).toBe(false);
        });
    });

    describe("deleteDomain", function() {

        it("calls deleteDomain", function() {
            var controller = makeController();
            var deleteDomain = spyOn(DomainsManager, "deleteDomain");
            var defer = $q.defer();
            deleteDomain.and.returnValue(defer.promise);
            $scope.deleteConfirmButton();
            expect(deleteDomain).toHaveBeenCalled();
        });
    });

});
